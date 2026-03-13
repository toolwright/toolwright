# Demo command: governance proof in under 1 second
# The instant wow moment — compile, block, drift, circuit breaker

Output demos/outputs/demo.gif
Output demos/outputs/demo.webm

Set FontSize 18
Set Width 900
Set Height 550
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

Type "toolwright demo"
Sleep 500ms
Enter
Sleep 6s

Sleep 3s
