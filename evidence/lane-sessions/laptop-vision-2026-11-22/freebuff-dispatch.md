# FreeBuff Lane 1 dispatch audit

| Step | State | Evidence |
| --- | --- | --- |
| Identify the existing FreeBuff window | Done | Harness captured only the bound FreeBuff window in 0.571s. The published [driver trace](freebuff-capture.jsonl) records the PNG hash. The PNG remains local because the app was showing another lane. |
| Bring FreeBuff forward | Blocked | Driver capture recorded `foreground: false`. The required live Jev decision was not dispatched. |
| Open existing Lane 1, thread `315608d2` | Blocked | The capture shows the Lane 1 entry under Harness. The driver never selected it, so the thread identity in the open view remains unverified. |
| Send or resume once | Blocked | The driver never inspected Lane 1's composer or mission controls and sent nothing. |
| Verify the platform response and Lane 1 state | Blocked | No send or platform response was observed. The owner's 45% usage reading gives context only. |

The dispatch requires live Jev decisions and prohibits payments. The recorded metered-inference and auto-recharge authorization covered the Notepad run. The FreeBuff run needs its own billing authorization. Ruff and 50 focused driver tests passed.
