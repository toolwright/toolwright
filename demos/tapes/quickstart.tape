# Full golden path: create → status → config in 60 seconds

Output demos/outputs/quickstart.gif
Output demos/outputs/quickstart.webm

Set FontSize 16
Set Width 900
Set Height 600
Set Theme "Molokai"
Set TypingSpeed 50ms
Set Padding 20
Set Shell "bash"

# Activate venv with clean prompt (hidden)
Hide
Type `export VIRTUAL_ENV_DISABLE_PROMPT=1 && source .venv/bin/activate && export PS1="$ " && clear`
Enter
Sleep 1s
Show

# Step 1: Create tools
Type "toolwright create github"
Sleep 500ms
Enter
Sleep 20s

# Step 2: Check status
Type "toolwright status"
Sleep 500ms
Enter
Sleep 3s

# Step 3: Get config
Type "toolwright config"
Sleep 500ms
Enter
Sleep 3s

Sleep 2s
