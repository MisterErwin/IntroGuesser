FROM alpine

RUN apk add --no-cache bash hostapd iptables dhcp docker iproute2 iw unbound nginx
RUN echo "" > /var/lib/dhcp/dhcpd.leases
# copy the unbound initial anchor (https://nlnetlabs.nl/documentation/unbound/howto-anchor/)
ADD trusted-key.key /etc/unbound/trusted-key.key
ADD nginx.conf /etc/nginx/nginx.conf

ADD wlanstart.sh /bin/wlanstart.sh

ENTRYPOINT [ "/bin/wlanstart.sh" ]