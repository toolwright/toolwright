# Hero demo: toolwright create github in 15 seconds
# Shows the "absurd benchmark" — 1062 governed tools from one command

Output demos/outputs/hero.gif
Output demos/outputs/hero.webm

Set FontSize 18
Set Width 900
Set Height 500
Set Theme "Molokai"
Set TypingSpeed 50ms
Set Padding 20
Set Shell "bash"
Set Framerate 24

# Activate venv with clean prompt (hidden)
Hide
Type `export VIRTUAL_ENV_DISABLE_PROMPT=1 && source .venv/bin/activate && export PS1="$ " && clear`
Enter
Sleep 1s
Show

Type "toolwright create github"
Sleep 500ms
Enter
Sleep 20s

Sleep 3s
