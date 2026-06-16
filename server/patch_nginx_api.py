from pathlib import Path

path = Path("/etc/nginx/sites-available/default")
text = path.read_text()
proxy = """\
\tlocation /api/ {
\t\tproxy_pass http://127.0.0.1:8787/api/;
\t\tproxy_http_version 1.1;
\t\tproxy_set_header Host $host;
\t\tproxy_set_header X-Real-IP $remote_addr;
\t\tproxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
\t\tproxy_set_header X-Forwarded-Proto $scheme;
\t}

"""

if "proxy_pass http://127.0.0.1:8787/api/" not in text:
    marker = "    server_name liuren.laowanghuofou.cn; # managed by Certbot\n\n\n\tlocation / {"
    replacement = "    server_name liuren.laowanghuofou.cn; # managed by Certbot\n\n\n" + proxy + "\tlocation / {"
    if marker not in text:
        raise SystemExit("target nginx server block marker not found")
    text = text.replace(marker, replacement, 1)
    path.write_text(text)

print("nginx api proxy present")
