#!/bin/bash -e

# Adapted version of the script by offlinehacker (https://github.com/offlinehacker/docker-ap)

# Check if running in privileged mode
if [ ! -w "/sys" ] ; then
    echo "[Error] Not running in privileged mode."
    exit 1
fi

# Default values
true ${INTERFACE:=wlan0}
true ${SUBNET:=192.168.254.0}
true ${AP_ADDR:=192.168.254.1}
true ${SSID:=IntroGuesser}
true ${CHANNEL:=11}
true ${HW_MODE:=g}
true ${DRIVER:=nl80211}
true ${HT_CAPAB:=[HT40-][SHORT-GI-20][SHORT-GI-40]}
true ${OUTGOINGS:=etho0}


# Attach interface to container
echo "Attaching interface to container"
CONTAINER_ID=$(cat /proc/self/cgroup | grep -o  -e "/docker/.*" | head -n 1| sed "s/\/docker\/\(.*\)/\\1/")
CONTAINER_PID=$(docker inspect -f '{{.State.Pid}}' ${CONTAINER_ID})
CONTAINER_IMAGE=$(docker inspect -f '{{.Config.Image}}' ${CONTAINER_ID})

docker run -t --privileged --net=host --pid=host --rm --entrypoint /bin/sh ${CONTAINER_IMAGE} -c "
    PHY=\$(echo phy\$(iw dev ${INTERFACE} info | grep wiphy | tr ' ' '\n' | tail -n 1))
    echo iw phy \$PHY set netns ${CONTAINER_PID}
    iw phy \$PHY set netns ${CONTAINER_PID}
"
# Reset via
# sudo iw phy phy0 set netns $(pidof NetworkManager) && sudo service network-manager restart

echo "Preparing hostapd"
# Setup an open WPA network

if [ ! -f "/etc/hostapd.conf" ] ; then
    cat > "/etc/hostapd.conf" <<EOF
interface=${INTERFACE}
driver=${DRIVER}
ssid=${SSID}
hw_mode=${HW_MODE}
channel=${CHANNEL}
wpa=0
wpa_pairwise=CCMP
rsn_pairwise=CCMP
wpa_ptk_rekey=600
ieee80211n=1
ht_capab=${HT_CAPAB}
wmm_enabled=1 
auth_algs=1
EOF

fi

# unblock wlan
rfkill unblock wlan

echo "Setting interface ${INTERFACE}"

# Setup interface and restart DHCP service
ip link set ${INTERFACE} up
echo "flushing interface"
ip addr flush dev ${INTERFACE}
echo "adding range to interface"
ip addr add ${AP_ADDR}/24 dev ${INTERFACE}

# NAT settings
echo "Setting NAT settings: ip_dynaddr, ip_forward"

for i in ip_dynaddr ip_forward ; do 
  if [ $(cat /proc/sys/net/ipv4/$i) ]; then
    echo $i already 1 
  else
    echo "1" > /proc/sys/net/ipv4/$i
  fi
done

cat /proc/sys/net/ipv4/ip_dynaddr 
cat /proc/sys/net/ipv4/ip_forward

outInts="$(sed 's/,\+/ /g' <<<"${OUTGOINGS}")"
for outInt in ${outInts}
do
  echo "Setting iptables for outgoing traffics on ${outInt}..."
  iptables -t nat -D PREROUTING -p udp -m udp --dport 53 -j DNAT --to-destination ${AP_ADDR}:5353 > /dev/null 2>&1 || true
  iptables -t nat -A PREROUTING -p udp -m udp --dport 53 -j DNAT --to-destination ${AP_ADDR}:5353

  iptables -t nat -D PREROUTING -p tcp -m tcp --dport 53 -j DNAT --to-destination ${AP_ADDR}:5353 > /dev/null 2>&1 || true
  iptables -t nat -A PREROUTING -p tcp -m tcp --dport 53 -j DNAT --to-destination ${AP_ADDR}:5353

  iptables -t nat -D POSTROUTING -s ${SUBNET}/24 -o ${outInt} -d 192.168.244.0/24 -j MASQUERADE > /dev/null 2>&1 || true
  iptables -t nat -A POSTROUTING -s ${SUBNET}/24 -o ${outInt} -d 192.168.244.0/24 -j MASQUERADE

  iptables -D FORWARD -i ${outInt} -o ${INTERFACE} -m state --state RELATED,ESTABLISHED -j ACCEPT > /dev/null 2>&1 || true
  iptables -A FORWARD -i ${outInt} -o ${INTERFACE} -m state --state RELATED,ESTABLISHED -j ACCEPT

  iptables -D FORWARD -i ${INTERFACE} -d 192.168.244.0/24 -o ${outInt} -j ACCEPT > /dev/null 2>&1 || true
  iptables -A FORWARD -i ${INTERFACE} -d 192.168.244.0/24 -o ${outInt} -j ACCEPT

  iptables -D FORWARD -j REJECT --reject-with icmp-net-prohibited > /dev/null 2>&1 || true
  iptables -A FORWARD -j REJECT --reject-with icmp-net-prohibited
done

echo "Configuring DHCP server .."

cat > "/etc/dhcp/dhcpd.conf" <<EOF
option domain-name-servers ${AP_ADDR};
option subnet-mask 255.255.255.0;
option routers ${AP_ADDR};
subnet ${SUBNET} netmask 255.255.255.0 {
  range ${SUBNET::-1}100 ${SUBNET::-1}200;
}
EOF

echo "Starting DHCP server .."
dhcpd ${INTERFACE}

# Set up unbound. Redirect all DNS requests to the nginx site, except intro.guesser and introserv.guesser

cat > "/etc/unbound/unbound.conf" <<EOF
server:
  interface: ${AP_ADDR}
  port: 5353
  access-control: 127.0.0.0/8 allow
  access-control: ${SUBNET}/24 allow
  val-permissive-mode: yes
  use-syslog: yes
  verbosity: 3
  log-queries: yes
  log-replies: yes
  log-local-actions: yes
  log-servfail: yes
  do-daemonize: yes
  username: "unbound"
  directory: "/etc/unbound"
  trust-anchor-file: trusted-key.key
  do-not-query-localhost: no
  local-zone: "intro.guesser." redirect
  local-data: "intro.guesser. 1 A 192.168.244.11"
  local-zone: "introserv.guesser." redirect
  local-data: "introserv.guesser. 1 A 192.168.244.12"
  local-zone: "." redirect
  local-data: ". 1 A ${AP_ADDR}"
EOF

echo "Starting unbound"
unbound -v -c /etc/unbound/unbound.conf

echo "Starting nginx"
nginx

echo "Starting HostAP daemon ..."
/usr/sbin/hostapd /etc/hostapd.conf 


# sudo iw phy phy0 set netns $(pidof NetworkManager) && sudo service network-manager restart
