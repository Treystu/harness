gaps = {
    "harness/availability.py": [67, 128, 131, 135, 150, 171, 216, 221, 237, 251, 325, 329, 330, 332, 334, 339, 345, 352],
    "harness/chat_policy.py": [142, 163],
    "harness/conversation_lifecycle.py": [216, 218],
    "harness/edit_lifecycle.py": [192, 251, 252, 265, 266, 267, 268, 270, 271, 272, 351, 361, 363, 364, 369, 370, 371, 372, 375, 376],
    "harness/hourglass_lifecycle.py": [172, 174, 175, 214, 216, 224],
    "harness/panel.py": [112, 114, 115, 117, 118, 121, 367, 369, 370, 371, 378, 382, 383, 385],
    "harness/simple_answer_lifecycle.py": [273, 276],
    "harness/waist.py": [605, 612, 613, 614, 616, 618, 620, 621, 624, 625, 626, 627, 629, 630, 631, 641, 1768],
    "harness/workspace.py": [56, 57, 58],
}

for rel, lines in gaps.items():
    src = open(rel, encoding="utf-8").read().splitlines()
    print(f"\n===== {rel} =====")
    lo = max(1, min(lines) - 14)
    hi = min(len(src), max(lines) + 8)
    for i in range(lo, hi + 1):
        mark = "*" if i in lines else " "
        print(f"{mark}{i:5d}: {src[i-1]}")
