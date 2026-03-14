from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from flask import Blueprint, jsonify, request
from google.api_core.exceptions import ResourceExhausted

from routes.shared import (
    broadcast_customer_updates,
    broadcast_products_onhand_updated,
    create_simple_fetch_handler,
    handle_api_errors,
    invalidate_invoice_cache,
    is_valid_pid,
    notify_daily_summary,
    notify_invoice_created,
    notify_invoice_deleted,
    notify_invoice_updated,
    notify_monthly_summary,
    notify_top_products,
    notify_yearly_summary,
    safe_float,
    safe_int,
    to_number,
)


def create_firebase_invoices_bp(invoice_service, product_service, customer_service, socketio) -> Blueprint:
    bp = Blueprint("firebase_invoices", __name__, url_prefix="/api/firebase")

    @bp.route("/invoices/<invoice_id>", methods=["GET"])
    @handle_api_errors
    def get_invoice_by_id(invoice_id: str):
        invoice = invoice_service.read_invoice(invoice_id)
        if invoice:
            return jsonify(invoice)
        return jsonify({"status": "error", "message": "Invoice not found"}), 404

    @bp.route("/add_invoice", methods=["POST"])
    def add_invoice():
        try:
            invoice = request.get_json(silent=True) or {}
            invoice_id = invoice.get("id") or invoice.get("Id")
            if invoice_id is None:
                return jsonify({"status": "error", "message": "invoice id is required"}), 400

            normalized_invoice = dict(invoice)
            normalized_invoice["id"] = str(invoice_id).strip()

            result = invoice_service.add_invoice(normalized_invoice)

            # Return response immediately after invoice is saved
            notify_invoice_created(socketio, normalized_invoice)
            response = dict(result)

            # Run post-write tasks in background (summary, customer, cache)
            def _background_tasks():
                try:
                    with ThreadPoolExecutor(max_workers=3) as executor:
                        f_cache = executor.submit(invalidate_invoice_cache, customer_service, normalized_invoice)
                        f_summary = executor.submit(invoice_service.adjust_invoice_summaries, normalized_invoice, 1)
                        f_customer = executor.submit(customer_service.apply_invoice_delta, None, normalized_invoice)

                        f_cache.result()
                        f_summary.result()
                        customer_results = f_customer.result()

                    customer_broadcasts = [r for r in customer_results if r.get("applied") and r.get("customer")]
                    if customer_broadcasts:
                        broadcast_customer_updates(socketio, customer_broadcasts)
                except Exception as exc:
                    import traceback
                    print(f"Background task error for invoice {normalized_invoice.get('id')}: {traceback.format_exc()}")

            import threading
            threading.Thread(target=_background_tasks, daemon=True).start()

            return jsonify(response)
        except ResourceExhausted as exc:
            import traceback
            print(traceback.format_exc())
            return jsonify({"status": "error", "message": "Firestore quota exceeded", "details": str(exc)}), 429
        except Exception as exc:
            import traceback
            print(traceback.format_exc())
            return jsonify({"status": "error", "message": str(exc)}), 500

    @bp.route("/invoices/<invoice_id>", methods=["PUT"])
    def update_invoice(invoice_id: str):
        try:
            updates = request.get_json(silent=True) or {}
            existing_invoice = invoice_service.read_invoice(invoice_id)

            result = invoice_service.update_invoice(invoice_id, updates)

            updated_invoice = invoice_service.read_invoice(invoice_id)

            if existing_invoice:
                invalidate_invoice_cache(customer_service, existing_invoice)
            if updated_invoice:
                invalidate_invoice_cache(customer_service, updated_invoice)

            # ✅ NEW: Handle summary changes
            summary_adjustments = []
            
            # Reverse old summary
            if existing_invoice:
                old_summary_result = invoice_service.adjust_invoice_summaries(
                    existing_invoice, direction=-1
                )
                if old_summary_result.get("updated"):
                    summary_adjustments.append(("old", old_summary_result))
            
            # Apply new summary
            if updated_invoice:
                new_summary_result = invoice_service.adjust_invoice_summaries(
                    updated_invoice, direction=1
                )
                if new_summary_result.get("updated"):
                    summary_adjustments.append(("new", new_summary_result))

            # ✅ Update customer totals using incremental delta (no full recalculate)
            customer_results = customer_service.apply_invoice_delta(
                previous_invoice=existing_invoice,
                new_invoice=updated_invoice,
            )
            customer_broadcasts = [r for r in customer_results if r.get("applied") and r.get("customer")]
            if customer_broadcasts:
                broadcast_customer_updates(socketio, customer_broadcasts)
            if updated_invoice:
                notify_invoice_updated(socketio, updated_invoice)

            response = dict(result)
            if summary_adjustments:
                response["summary_adjusted"] = summary_adjustments

            return jsonify(response)
        except ResourceExhausted as exc:
            import traceback
            print(traceback.format_exc())
            return jsonify({"status": "error", "message": "Firestore quota exceeded", "details": str(exc)}), 429
        except Exception as exc:
            import traceback
            print(traceback.format_exc())
            return jsonify({"status": "error", "message": str(exc)}), 500

    @bp.route("/invoices/<invoice_id>", methods=["DELETE"])
    def delete_invoice(invoice_id: str):
        try:
            existing_invoice = invoice_service.read_invoice(invoice_id)
            if not existing_invoice:
                return jsonify({"status": "error", "message": "Invoice not found"}), 404
            restocked_updates = []
            restock_errors = []
            cart_items = existing_invoice.get('cartItems', []) or []

            # ✅ FIX: Nếu invoice có isMergeEnabled=true, product gốc (original/KiotViet)
            # chưa bao giờ bị trừ tồn kho (chỉ lưu vào danh sách gộp), nên KHÔNG restock OnHand.
            # Clone products vẫn restock bình thường vì OnHandNV đã bị trừ khi checkout.
            is_merge_enabled = existing_invoice.get('isMergeEnabled') is True

            for item in cart_items:
                product_data = item.get('product') or {}
                product_id = product_data.get('Id') or product_data.get('id') or item.get('productId')
                quantity = safe_int(item.get('quantity', 0))
                if quantity <= 0:
                    continue
                pid_str = str(product_id) if product_id is not None else None
                if not is_valid_pid(pid_str):
                    continue
                product_doc = product_service.read_product(pid_str)
                if not product_doc:
                    continue

                # ✅ FIX: Check if product is a clone - clones use OnHandNV, not OnHand
                is_clone = product_doc.get('isClone') is True or product_doc.get('isClone') == "true"

                if is_clone:
                    # ✅ Clone product: update OnHandNV for ALL siblings in the group
                    # Get MasterUnitId to find all siblings
                    master_unit_id = product_doc.get('MasterUnitId') or product_doc.get('Id')
                    conversion_value = to_number(product_doc.get('ConversionValue', 1)) or 1

                    # Calculate delta in master unit terms
                    master_qty_delta = quantity * conversion_value

                    # Find all siblings with the same MasterUnitId
                    siblings = product_service.get_products_by_master_unit_id(str(master_unit_id))

                    if siblings and len(siblings) > 0:
                        print(f"  🔄 Clone product {pid_str}: Found {len(siblings)} siblings for MasterUnitId {master_unit_id}")
                        for sibling in siblings:
                            sibling_id = str(sibling.get('Id'))
                            sibling_conversion = to_number(sibling.get('ConversionValue', 1)) or 1
                            sibling_current_nv = to_number(sibling.get('OnHandNV', 0)) or 0

                            # Calculate sibling's delta based on its ConversionValue
                            sibling_delta = master_qty_delta / sibling_conversion if sibling_conversion != 0 else 0
                            sibling_new_nv = sibling_current_nv + sibling_delta

                            try:
                                product_service.update_product(sibling_id, {"OnHandNV": sibling_new_nv})
                                restocked_updates.append({"Id": sibling_id, "OnHandNV": sibling_new_nv, "updateType": "OnHandNV"})
                                print(f"    ✅ Sibling {sibling_id} (CV={sibling_conversion}): OnHandNV {sibling_current_nv} → {sibling_new_nv}")
                            except Exception as exc:
                                import traceback
                                print(f"Error restocking clone sibling {sibling_id}: {exc}")
                                print(traceback.format_exc())
                                restock_errors.append({"id": sibling_id, "error": str(exc)})
                    else:
                        # Fallback: just update the single product if no siblings found
                        current_onhand_nv = to_number(product_doc.get('OnHandNV', 0)) or 0
                        new_onhand_nv = current_onhand_nv + quantity
                        try:
                            product_service.update_product(pid_str, {"OnHandNV": new_onhand_nv})
                            restocked_updates.append({"Id": pid_str, "OnHandNV": new_onhand_nv, "updateType": "OnHandNV"})
                            print(f"  ✅ Clone product {pid_str}: OnHandNV restored {current_onhand_nv} → {new_onhand_nv} (no siblings)")
                        except Exception as exc:
                            import traceback
                            print(f"Error restocking clone product {pid_str}: {exc}")
                            print(traceback.format_exc())
                            restock_errors.append({"id": pid_str, "error": str(exc)})
                    continue

                # ✅ FIX: Nếu isMergeEnabled, product gốc chưa bị trừ tồn kho → skip restock
                if is_merge_enabled:
                    print(f"  ⏭️ Skipping restock for original product {pid_str} (isMergeEnabled=true, stock was never deducted)")
                    continue

                # Original product: update OnHand for ALL siblings in the group
                master_unit_id = product_doc.get('MasterUnitId') or product_doc.get('Id')
                conversion_value = to_number(product_doc.get('ConversionValue', 1)) or 1

                # Calculate delta in master unit terms
                master_qty_delta = quantity * conversion_value

                # Find all siblings with the same MasterUnitId
                siblings = product_service.get_products_by_master_unit_id(str(master_unit_id))

                if siblings and len(siblings) > 0:
                    print(f"  🔄 Original product {pid_str}: Found {len(siblings)} siblings for MasterUnitId {master_unit_id}")
                    for sibling in siblings:
                        sibling_id = str(sibling.get('Id'))
                        sibling_conversion = to_number(sibling.get('ConversionValue', 1)) or 1
                        sibling_current = to_number(sibling.get('OnHand', 0)) or 0

                        # Calculate sibling's delta based on its ConversionValue
                        sibling_delta = master_qty_delta / sibling_conversion if sibling_conversion != 0 else 0
                        sibling_new = sibling_current + sibling_delta

                        try:
                            product_service.update_product(sibling_id, {"OnHand": sibling_new})
                            restocked_updates.append({"Id": sibling_id, "OnHand": sibling_new, "updateType": "OnHand"})
                            print(f"    ✅ Sibling {sibling_id} (CV={sibling_conversion}): OnHand {sibling_current} → {sibling_new}")
                        except Exception as exc:
                            import traceback
                            print(f"Error restocking sibling {sibling_id}: {exc}")
                            print(traceback.format_exc())
                            restock_errors.append({"id": sibling_id, "error": str(exc)})
                else:
                    # Fallback: just update the single product if no siblings found
                    current_onhand = to_number(product_doc.get('OnHand'))
                    if current_onhand is None:
                        continue
                    new_onhand = int(current_onhand) + quantity
                    try:
                        product_service.update_product(pid_str, {"OnHand": new_onhand})
                        restocked_updates.append({"Id": pid_str, "OnHand": new_onhand, "updateType": "OnHand"})
                        print(f"  ✅ Original product {pid_str}: OnHand restored {current_onhand} → {new_onhand} (no siblings)")
                    except Exception as exc:
                        import traceback
                        print(f"Error restocking product {pid_str}: {exc}")
                        print(traceback.format_exc())
                        restock_errors.append({"id": pid_str, "error": str(exc)})
            
            # ✅ Adjust summaries (reverse the invoice)
            summary_adjustment = invoice_service.adjust_invoice_summaries(existing_invoice, direction=-1)

            delete_result = invoice_service.delete_invoice(invoice_id)

            invalidate_invoice_cache(customer_service, existing_invoice)

            # ✅ Update customer totals using incremental delta (reverse the invoice)
            customer_results = customer_service.apply_invoice_delta(
                previous_invoice=existing_invoice,
                new_invoice=None,
            )
            customer_broadcasts = [r for r in customer_results if r.get("applied") and r.get("customer")]
            if customer_broadcasts:
                broadcast_customer_updates(socketio, customer_broadcasts)

            notify_invoice_deleted(socketio, invoice_id)

                # Filter out error entries for the broadcast
            broadcast_products_onhand_updated(socketio, restocked_updates)

            response = {
                "message": delete_result.get("message", "invoice deleted"),
                "restocked_products": restocked_updates,
            }
            if summary_adjustment.get("updated"):
                response["summary_adjustment"] = summary_adjustment
            if restock_errors:
                response["restock_errors"] = restock_errors

            return jsonify(response)
        except ResourceExhausted as exc:
            import traceback
            print(traceback.format_exc())
            return jsonify({"status": "error", "message": "Firestore quota exceeded", "details": str(exc)}), 429
        except Exception as exc:
            import traceback
            print(traceback.format_exc())
            return jsonify({"status": "error", "message": str(exc)}), 500

    @bp.route("/invoices/fetch", methods=["POST"])
    def fetch_invoices_changed():
        """
        Accepts JSON: { "id": "123" } or { "ids": ["1","2"] }
        Returns the latest invoice document(s) from Firestore.
        """
        return create_simple_fetch_handler(invoice_service, "read_invoice")()

    @bp.route("/invoices/date", methods=["GET"])
    @handle_api_errors
    def get_invoices_by_date():
        date = request.args.get('date')
        if not date:
            return jsonify({"status": "error", "message": "date is required"}), 400
        invoices = invoice_service.get_invoices_by_date(date)
        return jsonify(invoices)

    @bp.route("/invoices/status/<status>", methods=["GET"])
    @handle_api_errors
    def get_invoices_by_status(status: str):
        invoices = invoice_service.get_invoices_by_status(status)
        return jsonify(invoices)

    @bp.route("/invoices/customer/<customer_id>", methods=["GET"])
    @handle_api_errors
    def get_invoices_by_customer(customer_id: str):
        invoices = invoice_service.get_invoices_by_customer(customer_id)
        return jsonify(invoices)

    @bp.route("/daily_summary", methods=["GET"])
    @handle_api_errors
    def get_daily_summary():
        date = request.args.get('date')
        if not date:
            return jsonify({"status": "error", "message": "date is required (YYYY-MM-DD)"}), 400
        summary = invoice_service.get_daily_summary(date)
        notify_daily_summary(socketio, date, summary)
        return jsonify(summary)

    @bp.route("/monthly_summary", methods=["GET"])
    @handle_api_errors
    def get_monthly_summary():
        year = request.args.get('year')
        month = request.args.get('month')
        if not year or not month:
            return jsonify({"status": "error", "message": "year and month are required"}), 400
        summary = invoice_service.get_monthly_summary(year, month)
        notify_monthly_summary(socketio, year, month, summary)
        return jsonify(summary)

    @bp.route("/yearly_summary", methods=["GET"])
    @handle_api_errors
    def get_yearly_summary():
        year = request.args.get('year')
        if not year:
            return jsonify({"status": "error", "message": "year is required"}), 400
        summary = invoice_service.get_yearly_summary(year)
        notify_yearly_summary(socketio, year, summary)
        return jsonify(summary)

    @bp.route("/top_products", methods=["GET"])
    @handle_api_errors
    def get_top_products():
        date = request.args.get('date')
        year = request.args.get('year')
        month = request.args.get('month')
        if date:
            invoices = invoice_service.get_invoices_by_date(date)
        elif year and month:
            from calendar import monthrange

            days_in_month = monthrange(int(year), int(month))[1]
            invoices = []
            for day in range(1, days_in_month + 1):
                date_str = f"{year}-{str(month).zfill(2)}-{str(day).zfill(2)}"
                invoices.extend(invoice_service.get_invoices_by_date(date_str))
        elif year:
            invoices = []
            for m in range(1, 13):
                from calendar import monthrange

                days_in_month = monthrange(int(year), m)[1]
                for day in range(1, days_in_month + 1):
                    date_str = f"{year}-{str(m).zfill(2)}-{str(day).zfill(2)}"
                    invoices.extend(invoice_service.get_invoices_by_date(date_str))
        else:
            invoices = list(invoice_service.stream_invoices())

        product_sales = {}
        for invoice in invoices:
            cart_items = invoice.get('cartItems', [])
            for item in cart_items:
                product = item.get('product', {})
                product_id = product.get('Id')
                product_name = product.get('FullName', 'Unknown')
                price = safe_float(product.get('BasePrice', 0))
                quantity = safe_int(item.get('quantity', 0))
                cost = safe_float(product.get('Cost', 0))
                total_profit = (price - cost) * quantity
                if product_id is not None:
                    if product_id not in product_sales:
                        product_sales[product_id] = {
                            'productId': product_id,
                            'productName': product_name,
                            'totalProfit': 0,
                            'totalQuantity': 0,
                        }
                    product_sales[product_id]['totalProfit'] += total_profit
                    product_sales[product_id]['totalQuantity'] += quantity
        top_products = sorted(product_sales.values(), key=lambda x: x['totalProfit'], reverse=True)[:20]
        filters = {}
        if date:
            filters['date'] = date
        if year:
            filters['year'] = year
        if month:
            filters['month'] = month
        notify_top_products(socketio, filters, top_products)
        return jsonify(top_products)
    @bp.route("/notify_change", methods=["POST"])
    @handle_api_errors
    def notify_change():
        """Accept a notification from a client that data changed and broadcast
        a simple event to other connected clients. This endpoint DOES NOT update
        application data; it only notifies other clients they should refresh.

        Expected JSON body example:
          { "namespace": "invoices", "event": "invoice_created", "data": { "id": "123" }, "sender_sid": "<optional-socket-sid>" }

        Allowed namespaces: `invoices`, `products`, `customers`, `orders`.
        If `sender_sid` is provided, it will be used as `skip_sid` to avoid
        echoing the notification back to the sender socket.
        """
        payload = request.get_json(silent=True) or {}
        namespace = (payload.get("namespace") or "invoices").strip()
        event = (payload.get("event") or "data_changed").strip()
        data = payload.get("data") or {}
        sender_sid = payload.get("sender_sid")

        allowed = {"invoices", "products", "customers", "orders"}
        if namespace not in allowed:
            return jsonify({"status": "error", "message": "invalid namespace"}), 400

        ns_path = f"/api/websocket/{namespace}"

        if not socketio:
            return jsonify({"status": "error", "message": "socketio not available"}), 500

        # store last notify for the namespace so new connections receive it on connect
        try:
            from routes.firebase_websocket import set_last_notify

            set_last_notify(ns_path, event, data)
        except Exception:
            pass

        # If sender_sid supplied, skip sending to that socket id (avoid echo)
        emit_kwargs = {"namespace": ns_path}
        if sender_sid:
            emit_kwargs["skip_sid"] = sender_sid

        socketio.emit(event, data, **emit_kwargs)

        return jsonify({"status": "ok", "namespace": namespace, "event": event})

    return bp
