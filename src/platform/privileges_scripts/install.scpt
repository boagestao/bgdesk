on run {daemon_file, agent_file, user}

  set daemon_plist to "/Library/LaunchDaemons/com.carriez.RustDesk_service.plist"
  set agent_plist to "/Library/LaunchAgents/com.carriez.RustDesk_server.plist"
  set prefs_dir to "/var/root/Library/Preferences/com.carriez.RustDesk/"
  set user_prefs to "/Users/" & user & "/Library/Preferences/com.carriez.RustDesk/"

  set sh1 to "echo " & quoted form of daemon_file & " > " & daemon_plist & " && chown root:wheel " & daemon_plist & ";"

  set sh2 to "echo " & quoted form of agent_file & " > " & agent_plist & " && chown root:wheel " & agent_plist & ";"

  set sh3 to "mkdir -p " & prefs_dir & " && cp -f " & user_prefs & "RustDesk.toml " & prefs_dir & " 2>/dev/null || true;"

  set sh4 to "cp -f " & user_prefs & "RustDesk2.toml " & prefs_dir & " 2>/dev/null || true;"

  set sh5 to "launchctl load -w " & daemon_plist & ";"

  set resolve_uid to "uid=$(id -u " & quoted form of user & " 2>/dev/null || true);"
  set agent_label_cmd to "agent_label=$(basename " & quoted form of agent_plist & " .plist);"
  set bootstrap_agent to "if [ -n \"$uid\" ]; then launchctl bootstrap gui/$uid " & quoted form of agent_plist & " 2>/dev/null || launchctl bootstrap user/$uid " & quoted form of agent_plist & " 2>/dev/null || launchctl load -w " & quoted form of agent_plist & " || true; else launchctl load -w " & quoted form of agent_plist & " || true; fi;"
  set kickstart_agent to "if [ -n \"$uid\" ]; then launchctl kickstart -k gui/$uid/$agent_label 2>/dev/null || launchctl kickstart -k user/$uid/$agent_label 2>/dev/null || true; fi;"
  set sh6 to resolve_uid & agent_label_cmd & bootstrap_agent & kickstart_agent

  set sh to sh1 & sh2 & sh3 & sh4 & sh5 & sh6

  do shell script sh with prompt "RustDesk wants to install daemon and agent" with administrator privileges
end run
