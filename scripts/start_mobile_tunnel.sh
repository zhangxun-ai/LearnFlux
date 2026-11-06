#!/bin/zsh
set -eu

edge_address() {
  local interface
  interface=$(/sbin/route -n get default 2>/dev/null | /usr/bin/awk '/interface:/ {print $2; exit}')
  if [[ -z "$interface" || "$interface" == utun* ]]; then
    interface=$(/usr/sbin/scutil --nwi | /usr/bin/awk '/IPv4 network interface information/ {v4=1; next} /IPv6 network interface information/ {v4=0} v4 && $2 == ":" && $1 !~ /^utun/ {print $1; exit}')
  fi
  [[ -n "$interface" ]] && /usr/sbin/ipconfig getifaddr "$interface" 2>/dev/null
}

address=$(edge_address) || address=""
if [[ -z "$address" ]]; then
  print -u2 "Waiting for a physical interface with an IPv4 address."
  exit 75
fi

/opt/homebrew/bin/cloudflared tunnel --no-autoupdate --config "$HOME/.config/learnflux-mobile/tunnel.yml" --edge-bind-address "$address" run &
tunnel_pid=$!

stop_tunnel() {
  kill -TERM "$tunnel_pid" 2>/dev/null || true
  wait "$tunnel_pid" || true
}
trap 'stop_tunnel; exit 0' TERM INT HUP

while kill -0 "$tunnel_pid" 2>/dev/null; do
  /bin/sleep 5
  current_address=$(edge_address) || continue
  if [[ -n "$current_address" && "$current_address" != "$address" ]]; then
    print -u2 "Tunnel edge address changed. Restarting with the current address."
    stop_tunnel
    exit 75
  fi
done

wait "$tunnel_pid"
