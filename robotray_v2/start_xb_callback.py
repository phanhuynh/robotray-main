# This file contains the Start XB callback logic
# It will be inserted into robotray_dash.py

@app.callback(
    Output("x550-combo-sequence-store", "data", allow_duplicate=True),
    Output("x550-combo-sequence-status", "children", allow_duplicate=True),
    Output("basler-photo-frame", "children", allow_duplicate=True),
    Input("btn-x550-start-combo-sequence-3-basler", "n_clicks"),
    State("x550-combo-count", "value"),
    State("store-x550", "data"),
    State("store-sample-type", "data"),
    State("store-basler", "data"),
    State("store-video-zoom", "data"),
    prevent_initial_call=True,
)
def start_x550_and_basler_combined(_n_clicks, combo_count, x550_data, sample_type, basler_data, zoom):
    """Start X550 combo sequence 3, then Basler sequence with shared test numbers and folder"""
    import cv2
    import datetime
    import requests
    import csv
    
    global TRAY_SEQUENCE_ROW, FIRST_CUP_X, FIRST_CUP_Y, BASLER_FIRST_CUP_X, BASLER_FIRST_CUP_Y, TRAY_WORK_Z, TRAY_SEQUENCE_RUNNING

    log_button_click("Start XB (X550 + Basler)")

    # ===== PHASE 1: X550 COMBO SEQUENCE 3 =====
    print("\n" + "="*60)
    print("PHASE 1: X550 COMBO SEQUENCE 3")
    print("="*60)

    # Check sample type
    if not sample_type or sample_type == "not specified":
        msg = "[ERROR] Please specify a sample type before starting"
        print(f"[START XB] {msg}")
        return None, msg, dash.no_update

    # Check X550 connection
    if not x550_data or not x550_data.get("x550_connected"):
        msg = "[ERROR] X550 not connected"
        print(f"[START XB] {msg}")
        return None, msg, dash.no_update

    base_url = x550_data.get("x550_url")
    if not base_url:
        msg = "[ERROR] Missing base URL"
        print(f"[START XB] {msg}")
        return None, msg, dash.no_update

    if not combo_count or combo_count < 1:
        msg = "[ERROR] Invalid count"
        print(f"[START XB] {msg}")
        return None, msg, dash.no_update

    # Move to first cup
    if _TRAY_INSTANCE and _TRAY_INSTANCE.is_connected():
        try:
            _TRAY_INSTANCE.goto(x=FIRST_CUP_X, y=FIRST_CUP_Y, z=0)
            print(f"[START XB] Moved to first cup (X={FIRST_CUP_X}, Y={FIRST_CUP_Y})")
            time.sleep(5)
            print("[START XB] Tray settled (5s pause)")
        except Exception as e:
            msg = f"[ERROR] Could not move to first cup: {e}"
            print(f"[START XB] {msg}")
            import traceback
            traceback.print_exc()
            return None, msg, dash.no_update
    else:
        msg = "[ERROR] Tray not connected"
        print(f"[START XB] {msg}")
        return None, msg, dash.no_update

    # Reset sequence row
    TRAY_SEQUENCE_ROW = 2
    print(f"[START XB] Reset tray sequence to row {TRAY_SEQUENCE_ROW}")

    # Get save folder
    test_subfolder = SAVED_FOLDER

    # Get first test number
    first_test_num = get_next_test_number()
    print(f"[START XB] First test number: {first_test_num:06d}")

    # For X550: we'll need to return values, but we're running both now
    # Store test numbers for basler phase
    x550_test_numbers = [first_test_num]
    first_num = None
    last_num = None
    results = []
    current_status = ""

    # Run X550 tests
    test_num = first_test_num
    try:
        for i in range(combo_count):
            if i > 0:
                test_num = get_next_test_number()
                x550_test_numbers.append(test_num)
            
            if first_num is None:
                first_num = test_num
            last_num = test_num

            now = datetime.datetime.now()
            timestamp = now.strftime("%Y_%m_%d_%H%M%S") + f"{int(now.microsecond / 10000):02d}"

            log_button_click("Combo Test 3 (X550)", test_number=f"{test_num:06d}")
            chemistry_rows = []

            # Mining test
            app_mode = "Mining"
            test_url = f"{base_url}/api/v2/test/final"
            print(f"[START XB] X550 Test {i+1}/{combo_count}: Running Mining test - {test_num:06d}")
            test_r = requests.post(test_url, params={"mode": app_mode}, json={}, timeout=60)

            if test_r.ok:
                mining_result = test_r.json()
                print(f"[START XB] Mining result: {mining_result}")
                results.append(("Mining", mining_result))
                current_status = f"Mining complete: {test_num:06d}"
            else:
                current_status = f"Mining failed (HTTP {test_r.status_code})"
                print(f"[START XB] {current_status}")

            # Save X550 screenshot
            try:
                screenshot_path = os.path.join(test_subfolder, f"{test_num:06d}_{timestamp}_x550.png")
                save_x550_screenshot(base_url, screenshot_path)
            except Exception as e:
                print(f"[START XB] Warning: Could not save X550 screenshot: {e}")

            # Execute Forward after each test (except last)
            if i < combo_count - 1:
                try:
                    print(f"[START XB] Executing Forward button (X550)")
                    if not _TRAY_INSTANCE or not _TRAY_INSTANCE.is_connected():
                        current_status = "[WARN] Tray not connected - Forward skipped"
                        print("[START XB] Tray not connected - Forward skipped")
                    else:
                        seq_file = os.path.join(os.path.dirname(__file__), 'tray_sequence.txt')
                        if os.path.exists(seq_file):
                            with open(seq_file, 'r') as f:
                                lines = f.readlines()
                            if TRAY_SEQUENCE_ROW < len(lines):
                                row_data = lines[TRAY_SEQUENCE_ROW].strip().split('\t')
                                if len(row_data) >= 2:
                                    try:
                                        x_delta = float(row_data[0])
                                        y_delta = float(row_data[1])
                                        _TRAY_INSTANCE._send("G91")
                                        if x_delta != 0 or y_delta != 0:
                                            _TRAY_INSTANCE._send(f"G0 X{x_delta} Y{y_delta} F3000")
                                        _TRAY_INSTANCE._send("G90")
                                        TRAY_SEQUENCE_ROW += 1
                                        current_status = f"Forward: X{x_delta:+.2f} Y{y_delta:+.2f} (Row {TRAY_SEQUENCE_ROW})"
                                        print(f"[START XB] Forward executed: X{x_delta:+.2f} Y{y_delta:+.2f}")
                                    except ValueError as ve:
                                        current_status = f"[WARN] Forward parse error: {ve}"
                            else:
                                current_status = f"[WARN] Reached end of sequence (row {TRAY_SEQUENCE_ROW})"
                                print(f"[START XB] Reached end of sequence")
                        else:
                            current_status = "[WARN] tray_sequence.txt not found"
                            print(f"[START XB] tray_sequence.txt not found")
                except Exception as e:
                    current_status = f"[WARN] Forward error: {e}"
                    print(f"[START XB] Error executing Forward: {e}")

    except Exception as e:
        print(f"[START XB] X550 error: {e}")
        import traceback
        traceback.print_exc()
        return None, f"[ERROR] X550 sequence failed: {e}", dash.no_update

    print(f"[START XB] X550 sequence complete. Test numbers used: {x550_test_numbers}")

    # ===== PHASE 2: BASLER SEQUENCE =====
    print("\n" + "="*60)
    print("PHASE 2: BASLER SEQUENCE")
    print("="*60)

    try:
        basler_msg, basler_preview = start_basler_three_shots(
            _n_clicks=None,
            basler_data=basler_data,
            sample_type=sample_type,
            zoom=zoom,
            override_test_numbers=x550_test_numbers,
            override_save_dir=test_subfolder
        )
        print(f"[START XB] Basler sequence result: {basler_msg}")
        
        final_x550_msg = f"[OK] X550 Combo sequence complete ({combo_count} tests)"
        final_msg = f"{final_x550_msg}\n{basler_msg}"
        
        log_button_click("Start XB Complete", is_button=False, total_tests=combo_count)
        
        return None, final_msg, basler_preview

    except Exception as e:
        print(f"[START XB] Basler error: {e}")
        import traceback
        traceback.print_exc()
        return None, f"[ERROR] Basler sequence failed: {e}", dash.no_update
