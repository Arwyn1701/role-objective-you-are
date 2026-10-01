# 會議室預約系統 (Meeting Room Reservation System)

> **HW2 會議室預約規格實現與五大商業規則驗證系統**  
> 具備完整規格描述檔、領域驅動設計程式碼架構、19 項單元測試（100% 通過）與現代化互動式視覺化看板。

🌐 **即時展示與互動測試網址：**  
👉 [https://antigravity.luch.dev/site/2fba26a0-049a-477c-bac5-447fd2c6d6cb/80ef339542722b1125b4541d/](https://antigravity.luch.dev/site/2fba26a0-049a-477c-bac5-447fd2c6d6cb/80ef339542722b1125b4541d/)

---

## 專案核心交付項目 (Project Deliverables)

1. **規格描述檔 (Specification Artifact):**
   - [`HW2_會議室預約_規格描述檔.md`](./HW2_會議室預約_規格描述檔.md)
   - 詳細規範五大商業規則判定公式、DDD 領域模型、狀態機轉移圖、循序圖與 19 項測試覆蓋清單。
2. **完整運作程式碼 (Working Program):**
   - [`reservation_system/`](./reservation_system/) 核心模組套件（Python 3.10+ 原生標準庫，無外部依賴）。
3. **自動化驗證測試腳本 (Verification Tests):**
   - [`test_reservation_system.py`](./test_reservation_system.py) 包含 19 項測試案例，完全通過驗證。
4. **互動式 Web 視覺化看板 (Web Application):**
   - [`index.html`](./index.html) 支援即時時程甘特軸、五大規則沙盒模擬器與即時測試套件運行器。

---

## 五大核心商業規則說明 (Core Business Rules)

| 編號 | 規則名稱 | 核心機制與說明 |
| :---: | :--- | :--- |
| **1** | **時段重疊 (Time Overlap)** | 採用左閉右開半開區間 $[S, E)$，同一會議室絕不允許在相同或交疊時段重複預約。重疊時拋出 `TimeOverlapError`。 |
| **2** | **緩衝時間 (Buffer Time)** | 自動在前後強制保留換場與清潔時間（例如 15 分鐘）。若相鄰間隔 $\Delta T < \text{buffer}$，阻擋並拋出 `BufferTimeViolationError`。 |
| **3** | **週期性會議 (Recurring Meetings)** | 支援每日、每週、隔週、每月等週期。提供 `ALL_OR_NOTHING`（任一期衝突全系列原子回滾）與 `ALLOW_PARTIAL` 雙原則。 |
| **4** | **臨時維護需求 (Temporary Maintenance)** | 維護時段（`MaintenanceWindow`）具備最高優先權。支援管理員覆蓋模式（`override_affected=True`）強制驅離受影響預約並標註 `CANCELLED_BY_MAINTENANCE`。 |
| **5** | **預約取消 (Reservation Cancellation)** | 取消預約後狀態轉為 `CANCELLED`，時段及前後緩衝時間**即刻釋出**，其他使用者可立即成功預約該時段。防止重複取消。 |

---

## 專案架構目錄 (Directory Structure)

```text
.
├── HW2_會議室預約_規格描述檔.md    # 核心作業交付規格文件 (DDD、狀態圖、循序圖、邊界矩陣)
├── README.md                      # 專案總覽文件 (本檔案)
├── index.html                     # 現代化互動看板與 5 大規則驗證 Web 沙盒
├── test_reservation_system.py    # 19 項自動化單元測試腳本
└── reservation_system/            # Python 領域程式碼套件
    ├── __init__.py                # 套件匯出介面
    ├── models.py                  # 領域實體 (Room, Reservation, MaintenanceWindow, TimeSlot)
    ├── conflict_checker.py        # 時段重疊、緩衝區計算、維護鎖定檢驗模組
    ├── recurrence_service.py      # 週期性會議生成與批次衝突評估器
    └── reservation_service.py     # 預約業務主服務 (Facade Pattern)
```

---

## 本地執行自動化測試 (Run Tests)

本專案無須安裝任何第三方套件，直接使用 Python 原生 `unittest` 執行：

```bash
python3 -m unittest -v test_reservation_system.py
```

### 測試執行結果 (19/19 PASS)：
```text
test_edge_case_start_after_end (test_reservation_system.TestMeetingRoomReservationSystem) ... ok
test_edge_case_zero_duration (test_reservation_system.TestMeetingRoomReservationSystem) ... ok
test_rule1_different_room_same_time_succeeds (test_reservation_system.TestMeetingRoomReservationSystem) ... ok
test_rule1_exact_overlap_fails (test_reservation_system.TestMeetingRoomReservationSystem) ... ok
test_rule1_partial_overlap_start_and_end (test_reservation_system.TestMeetingRoomReservationSystem) ... ok
test_rule1_subset_and_superset_overlap (test_reservation_system.TestMeetingRoomReservationSystem) ... ok
test_rule2_insufficient_buffer_gap_fails (test_reservation_system.TestMeetingRoomReservationSystem) ... ok
test_rule2_sufficient_buffer_gap_succeeds (test_reservation_system.TestMeetingRoomReservationSystem) ... ok
test_rule2_zero_gap_back_to_back_violates_buffer (test_reservation_system.TestMeetingRoomReservationSystem) ... ok
test_rule3_cancel_entire_series (test_reservation_system.TestMeetingRoomReservationSystem) ... ok
test_rule3_recurrence_all_or_nothing_fails_on_conflict (test_reservation_system.TestMeetingRoomReservationSystem) ... ok
test_rule3_recurrence_allow_partial (test_reservation_system.TestMeetingRoomReservationSystem) ... ok
test_rule3_weekly_recurrence_success (test_reservation_system.TestMeetingRoomReservationSystem) ... ok
test_rule4_cancelling_maintenance_frees_room (test_reservation_system.TestMeetingRoomReservationSystem) ... ok
test_rule4_maintenance_locks_out_new_reservations (test_reservation_system.TestMeetingRoomReservationSystem) ... ok
test_rule4_maintenance_with_override_cancels_existing_bookings (test_reservation_system.TestMeetingRoomReservationSystem) ... ok
test_rule4_maintenance_without_override_rejects_if_bookings_exist (test_reservation_system.TestMeetingRoomReservationSystem) ... ok
test_rule5_cancellation_releases_slot_and_buffer (test_reservation_system.TestMeetingRoomReservationSystem) ... ok
test_rule5_double_cancellation_rejected (test_reservation_system.TestMeetingRoomReservationSystem) ... ok

----------------------------------------------------------------------
Ran 19 tests in 0.008s

OK
```
