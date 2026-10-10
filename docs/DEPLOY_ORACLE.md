# Deploying on Oracle Cloud (Always Free) — step by step

This guide puts the invoice app on the internet at an address like **https://myinvoice.duckdns.org**,
for free, on an Oracle Cloud "Always Free" Arm virtual machine. Docker runs the app; Caddy provides
HTTPS automatically; DuckDNS gives you a free domain name.

You need: a credit/debit card (for identity verification only — see step 1), about an hour, and a
terminal on your own computer (PowerShell on Windows, Terminal on macOS/Linux).

```text
you ──https──▶ DuckDNS name ──▶ Oracle VM (Ubuntu) ──▶ Caddy (ports 80/443) ──▶ app (private network)
```

Commands in grey boxes are copied into a terminal. Replace anything in `CAPITALS_LIKE_THIS`.
Lines starting with `#` are comments — you don't need to type them.

---

## 1. Create an Oracle Cloud Free Tier account

1. Go to <https://www.oracle.com/cloud/free/> → **Start for free** and fill in the form.
2. **Choose your home region carefully.** It can never be changed, and Always Free resources exist
   only in the home region. Pick a region close to your users (and, if offered a choice, one that is
   less popular — Arm capacity there is usually easier to get).
3. Oracle asks for a card to verify your identity. A small temporary authorization may appear; it is
   released.
4. **Do not upgrade the account to "Pay As You Go".** Stay on the Free Tier:
   - On the Free Tier, if something ever exceeds the free limits, Oracle **stops** it — your card is
     never charged.
   - After an upgrade, anything beyond the free limits is **billed to your card**. A mistake (wrong
     shape, extra disk, a load balancer) would cost money.
5. New accounts start with a 30-day trial with credits. During the trial, **create only resources
   labeled "Always Free-eligible"**. Anything else is deleted when the trial ends (and is not needed
   for this app).

---

## 2. Create the virtual machine

1. In the Oracle Cloud console open the **☰ menu → Compute → Instances → Create instance**.
2. **Name:** e.g. `invoice`.
3. **Image and shape → Edit:**
   - **Image:** *Canonical Ubuntu* — the newest LTS (e.g. 24.04). With an Arm shape the console picks
     the **aarch64** build automatically.
   - **Shape:** *Change shape* → **Ampere** → **VM.Standard.A1.Flex**, then set **1 OCPU** and **2 GB**
     memory (it should show the "Always Free-eligible" label).

   Why so small when the free allowance is bigger? 1 OCPU / 2 GB runs this app comfortably (a
   1000-item PDF needs under 300 MB), leaves room in your free allowance, survives future allowance
   cuts, and — importantly — keeps **memory usage above 20 %**, which helps avoid Oracle's idle
   reclamation (see step 8).
4. **Networking:** keep the defaults (a new virtual cloud network with a *public subnet*) and make sure
   **Assign a public IPv4 address** is selected.
5. **Add SSH keys** — you need a key to log in. Create one on your own computer:

   ```bash
   # macOS / Linux
   ssh-keygen -t ed25519 -f ~/.ssh/oracle_invoice
   # Windows PowerShell
   ssh-keygen -t ed25519 -f $HOME\.ssh\oracle_invoice
   ```

   Press Enter for an empty passphrase (or set one). In the console choose **Upload public key files**
   and pick `oracle_invoice.pub` (the **.pub** file — never upload the private key).
6. **Boot volume:** keep the default size (about 47 GB is plenty and within the free 200 GB).
7. Click **Create**. After a minute the instance is **Running**. Copy its **Public IP address**.

**"Out of host capacity"?** Oracle has run out of free Arm machines at that moment. Try:
- another **availability domain** (AD-1/AD-2/AD-3) in the placement section, if your region has several;
- again later (capacity frees up during the day — early morning often works);
- as a last resort the x86 shape **VM.Standard.E2.1.Micro** (1 GB RAM, also Always Free). It is small:
  add swap and build the image elsewhere — see [Appendix: E2.1.Micro](#appendix-e21micro-fallback-x86-1-gb).

**Log in** from your computer (the username for Ubuntu images is `ubuntu`):

```bash
# macOS / Linux
ssh -i ~/.ssh/oracle_invoice ubuntu@PUBLIC_IP
# Windows PowerShell
ssh -i $HOME\.ssh\oracle_invoice ubuntu@PUBLIC_IP
```

Answer `yes` to the fingerprint question. Your prompt changes to `ubuntu@invoice:~$` — every command
from here on runs **on the VM** unless stated otherwise.

---

## 3. Open ports 80 and 443 — in TWO places

Web traffic must pass two firewalls: Oracle's network firewall *and* the firewall inside Ubuntu.
Forgetting either one is the most common reason the site is unreachable.

### 3a. The VCN security list (Oracle console)

1. Console → **Compute → Instances → invoice** → in *Instance details* click the **Virtual cloud
   network** link → **Security** (or **Security Lists**) → **Default Security List for …**
2. **Add Ingress Rules** — add two rules:

   | Source CIDR | IP Protocol | Destination Port Range | Description |
   |---|---|---|---|
   | `0.0.0.0/0` | TCP | `80` | HTTP (certificates + redirect) |
   | `0.0.0.0/0` | TCP | `443` | HTTPS |

   Optionally add the same for **UDP 443** (HTTP/3). Leave the existing SSH rule (port 22) alone.

### 3b. The VM's iptables firewall (on the VM)

Oracle's Ubuntu images ship with strict iptables rules that end in a **REJECT** rule. New ACCEPT rules
must go **before** that REJECT line. Do this **before installing Docker** (step 4).

```bash
# Show the rules with line numbers — note the line number of the REJECT rule
sudo iptables -L INPUT --line-numbers

# Insert the new rules just above the REJECT rule (this finds its line number for you)
REJECT_LINE=$(sudo iptables -L INPUT --line-numbers | awk '$2=="REJECT"{print $1; exit}')
sudo iptables -I INPUT "$REJECT_LINE" -p tcp -m state --state NEW --dport 80 -j ACCEPT
sudo iptables -I INPUT "$REJECT_LINE" -p tcp -m state --state NEW --dport 443 -j ACCEPT
sudo iptables -I INPUT "$REJECT_LINE" -p udp --dport 443 -j ACCEPT

# Check: the three new ACCEPT lines appear ABOVE the REJECT line
sudo iptables -L INPUT --line-numbers

# Make the rules survive reboots
sudo netfilter-persistent save
```

---

## 4. Install Docker and keep the system patched

Install Docker Engine and the Compose plugin from Docker's official repository (it detects arm64 by itself):

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Let the ubuntu user run docker without sudo, then log out and back in
sudo usermod -aG docker ubuntu
exit
```

Log in again (`ssh -i … ubuntu@PUBLIC_IP`) and check:

```bash
docker run --rm hello-world     # prints "Hello from Docker!"
docker compose version          # prints the Compose version
```

Docker starts automatically after every reboot, and the app's containers restart with it.

**Automatic security updates** (usually already on in Oracle's Ubuntu images — this makes sure):

```bash
sudo apt-get install -y unattended-upgrades
sudo dpkg-reconfigure --priority=low unattended-upgrades    # answer "Yes"
```

Updates are installed automatically; kernel updates take effect after a reboot (see step 8).

---

## 5. Get a free domain name from DuckDNS

1. Go to <https://www.duckdns.org> and sign in (GitHub, Google, …).
2. Type a name in **sub domain** (e.g. `myinvoice`) → **add domain**.
3. In the **current ip** box enter your VM's **public IP** → **update ip**.
   Your address is now `myinvoice.duckdns.org`.
4. Copy your **token** from the top of the DuckDNS page — it is a password, keep it private.

Oracle normally keeps the same public IP, but if it ever changes the site would break. A tiny
scheduled job on the VM re-registers the IP every 5 minutes:

```bash
mkdir -p ~/duckdns
cat > ~/duckdns/duck.sh <<'EOF'
#!/bin/sh
# Re-register this machine's public IP with DuckDNS (an empty ip= means "use the caller's IP").
curl -fsS "https://www.duckdns.org/update?domains=YOUR_SUBDOMAIN&token=YOUR_TOKEN&ip=" -o "$HOME/duckdns/duck.log"
EOF
nano ~/duckdns/duck.sh          # replace YOUR_SUBDOMAIN (e.g. myinvoice — without .duckdns.org) and YOUR_TOKEN
chmod 700 ~/duckdns/duck.sh     # only you can read it (it contains the token)

~/duckdns/duck.sh && cat ~/duckdns/duck.log    # must print: OK

# Run it every 5 minutes
(crontab -l 2>/dev/null; echo "*/5 * * * * $HOME/duckdns/duck.sh >/dev/null 2>&1") | crontab -
crontab -l                      # shows the new line
```

(In `nano`: edit, then **Ctrl+O**, **Enter** to save and **Ctrl+X** to exit.)

---

## 6. Deploy the app

### 6a. Put the code on the VM

**With Git (recommended):** push the project to a Git host such as GitHub (a private repository is
fine), then on the VM:

```bash
git clone https://github.com/YOUR_ACCOUNT/YOUR_REPOSITORY.git ~/invoice-app
cd ~/invoice-app
```

For a private GitHub repository, use a *fine-grained personal access token* with read access as the
password when `git clone` asks.

**Without Git:** copy the folder from your computer (run this **on your computer**, inside the project folder's parent):

```bash
scp -i ~/.ssh/oracle_invoice -r ./Invoice ubuntu@PUBLIC_IP:~/invoice-app
```

### 6b. Configure

```bash
cd ~/invoice-app
cp .env.example .env
nano .env
```

Set your domain and save:

```ini
DOMAIN=myinvoice.duckdns.org
```

Everything else can stay as it is (each setting is explained in the file).

### 6c. Start

```bash
docker compose up -d --build
```

The first build takes a few minutes (it downloads Ubuntu packages and Python libraries for Arm).
Then check:

```bash
docker compose ps                         # app: "healthy", caddy: "running"
docker compose logs caddy | grep -i "certificate obtained"
```

Caddy obtains the HTTPS certificate from Let's Encrypt within a minute of the first start.

### 6d. Verify

1. Open **https://myinvoice.duckdns.org** — the padlock shows a valid certificate.
2. Add two or three items, click **إنشاء PDF** — `invoice-YYYY-MM-DD.pdf` downloads.
3. `http://…` (without s) redirects to `https://…`.

You're live. 🎉

---

## 7. Updating to a new version

```bash
cd ~/invoice-app
git pull
docker compose up -d --build
docker image prune -f            # delete the previous, now unused image
```

(Without Git: copy the new files over with `scp` again, then run the last two commands.)

Changed only `.env`? Run `docker compose up -d` — the app restarts with the new settings.

---

## 8. Ongoing care

**Oracle's idle reclamation.** Oracle may reclaim (stop) an Always Free instance that looks idle for
7 days — when the 95th-percentile **CPU** usage, **network** usage *and* (on Arm shapes) **memory**
usage are **all below 20 %**. A quiet invoice app uses little CPU or network, so memory is what keeps
it "busy": with 2 GB, Ubuntu + Docker + the app normally use 25–35 %.

- **After the first week**, open Console → **Compute → Instances → invoice → Metrics** and look at
  *CPU utilization*, *Memory utilization* and *Network bytes*. If memory sits below 20 %, check on the
  VM with `free -m` (the *used* column) and keep an eye on it.
- **Log in to the Oracle console at least once a month** — it keeps the account active and lets you
  spot e-mails or warnings.
- **If Oracle ever stops the instance**, simply start it again: Console → Instances → invoice →
  **Start**. Docker and the app come back on their own.

**Disk space.** Container logs are already capped (10 MB × 3 files per container). Old images are the
main thing that piles up:

```bash
df -h /                      # free space on the disk
docker system df             # space used by Docker
docker image prune -f        # remove unused images (run after every update)
```

**Reboots for security updates.** When `/var/run/reboot-required` exists, reboot at a quiet moment:

```bash
ls /var/run/reboot-required 2>/dev/null && sudo reboot
```

The site is back about a minute later. Nothing needs backing up: the app stores no data. Keep a copy
of your `.env` and your SSH key somewhere safe.

---

## 9. Troubleshooting

### The site does not load at all

Work from the inside out:

```bash
docker compose ps                       # both containers up? app "healthy"?
curl -I http://localhost                # on the VM: Caddy answers (308 redirect)?
```

- Containers not running → `docker compose logs --tail 50` shows why; then `docker compose up -d`.
- Works on the VM but not from your computer → a **firewall**: check **both** places from step 3 —
  the security list rules (TCP 80 and 443 from `0.0.0.0/0`) and `sudo iptables -L INPUT --line-numbers`
  (the ACCEPT lines must be above REJECT).
- Check DNS from your computer: `nslookup myinvoice.duckdns.org` must return the VM's public IP.

### Caddy cannot get a certificate (browser shows a certificate error)

```bash
docker compose logs caddy | grep -iE "error|challenge|acme" | tail -20
```

- **DNS** must point to the VM (`nslookup` above) and `DOMAIN` in `.env` must be exactly that name.
- **Port 80** must be reachable from the internet — Let's Encrypt checks it. Re-check step 3.
- After fixing, `docker compose restart caddy`. Let's Encrypt limits repeated failures, so if you hit
  a "rate limit" message wait an hour before retrying. Do not delete the `caddy_data` volume — it holds
  your certificate.

### Reading logs

```bash
docker compose logs -f              # everything, live (Ctrl+C stops following)
docker compose logs --tail 100 app  # last 100 app lines: one per request, never invoice contents
docker compose logs --tail 100 caddy
```

### Users see «الخادم مشغول، حاول مرة أخرى بعد قليل»

That is the protection against abuse: more than `RATE_LIMIT_PER_MINUTE` PDFs per minute from one IP,
or all `MAX_CONCURRENT_RENDERS` slots busy for 10 seconds. Adjust in `.env` and run `docker compose up -d`.

### Turning a password on (optional)

Set `APP_PASSWORD=something-long` in `.env`, then `docker compose up -d`. Browsers then ask for a
username (anything) and that password.

---

## Appendix: E2.1.Micro fallback (x86, 1 GB)

Use this only if no Arm capacity is available. The steps are the same, except:

1. **Add swap** so the 1 GB machine doesn't run out of memory:

   ```bash
   sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
   sudo mkswap /swapfile && sudo swapon /swapfile
   echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
   ```

2. **Build the image on your own computer** instead of on the VM (building needs more memory), then copy
   it over. On your computer, in the project folder:

   ```bash
   docker build --platform linux/amd64 --target prod -t invoice-app:latest .
   docker save invoice-app:latest -o invoice-app.tar
   scp -i ~/.ssh/oracle_invoice invoice-app.tar ubuntu@PUBLIC_IP:~
   ```

   On the VM:

   ```bash
   docker load -i ~/invoice-app.tar && rm ~/invoice-app.tar
   cd ~/invoice-app && docker compose up -d      # note: no --build
   ```

3. Consider `MAX_CONCURRENT_RENDERS=1` in `.env` on this small machine.
