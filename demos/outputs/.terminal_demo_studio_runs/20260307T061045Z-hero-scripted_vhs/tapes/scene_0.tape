Output "/Users/thomasallicino/oss/toolwright/demos/outputs/.terminal_demo_studio_runs/20260307T061045Z-hero-scripted_vhs/scenes/scene_0.mp4"
Set FontSize 20
Set Framerate 60
Set LineHeight 1.15
Set LetterSpacing 0
Set Width 1440
Set Height 900
Set Theme "TokyoNightStorm"
Set Padding 24
Set Margin 12
Set MarginFill "#0F172A"
Set BorderRadius 10
Set CursorBlink false
Set WindowBar Colorful
Hide
Type "export PS1='\\nuser@dev ${PWD##*/} % '"
Enter
Type "cd /var/folders/wr/1tqp7q5s5q97slw283rp9h7h0000gn/T/toolwright_hero"
Enter
Type "export PATH=/Users/thomasallicino/oss/toolwright/.venv/bin:$PATH"
Enter
Type "mkdir -p .toolwright"
Enter
Type "clear"
Enter
Show
Type "toolwright demo --out ./demo"
Enter
Wait+Screen@20s /Pending:/
Sleep 1200ms
Type "clear"
Enter
Sleep 300ms
Type "python ./hero_proof.py blocked"
Enter
Wait+Screen@10s /denied_not_approved/
Sleep 1200ms
Type "toolwright gate allow --all --lockfile hero.lock.yaml --by ci@toolwright -y"
Enter
Wait+Screen@10s /Approved/
Sleep 1200ms
Type "clear"
Enter
Sleep 300ms
Type "python ./hero_proof.py allowed"
Enter
Wait+Screen@10s /Decision:\ allow/
Sleep 2s
