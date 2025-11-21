from flask import request, redirect, url_for
import ipaddress

def is_private_ip(ip):
    try:
        ip_obj = ipaddress.ip_address(ip)
        return ip_obj.is_private or ip_obj.is_loopback
    except ValueError:
        return False

@app.route('/2fa-setup', methods=['GET', 'POST'])
def twofa_setup():
    # Get client IP, considering reverse proxy
    ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if ip and ',' in ip:
        ip = ip.split(',')[0].strip()
    if is_private_ip(ip):
        # Skip 2FA setup for private IPs
        return redirect(url_for('dashboard'))  # or wherever you want to redirect
    # ...existing 2FA setup logic...