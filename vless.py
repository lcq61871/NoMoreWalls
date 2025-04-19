import requests
import yaml
import subprocess
import tempfile
import os
import time
import shutil

SUB_URLS = [
    "https://cdn.jsdelivr.net/gh/0xJins/x.sub@main/trials_providers/TW.yaml",
    "https://cdn.jsdelivr.net/gh/1wyy/tg_mfbpn_sub@main/trial.yaml"
]

CLASH_META_URL = "https://github.com/MetaCubeX/Clash.Meta/releases/latest/download/clash.meta-linux-amd64"
CLASH_META_BIN = "clash.meta"

def download_clash_meta():
    if not os.path.exists(CLASH_META_BIN):
        print("⬇️ Downloading Clash.Meta...")
        with requests.get(CLASH_META_URL, stream=True) as r:
            with open(CLASH_META_BIN, "wb") as f:
                shutil.copyfileobj(r.raw, f)
        os.chmod(CLASH_META_BIN, 0o755)

def fetch_vless_nodes():
    nodes = []
    for url in SUB_URLS:
        try:
            print(f"🔗 Fetching {url}")
            resp = requests.get(url, timeout=10)
            data = yaml.safe_load(resp.text)
            for proxy in data.get("proxies", []):
                if proxy.get("type") == "vless":
                    nodes.append(proxy)
        except Exception as e:
            print(f"❌ Failed to fetch {url}: {e}")
    return nodes

def run_clash_meta(config_path):
    return subprocess.Popen(
        [f"./{CLASH_META_BIN}", "-d", ".", "-f", config_path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

def test_real_delay(proxies):
    results = []
    tmp_config = {
        "mixed-port": 7890,
        "external-controller": "127.0.0.1:9090",
        "secret": "",
        "allow-lan": False,
        "mode": "rule",
        "log-level": "silent",
        "proxies": proxies,
        "proxy-groups": [
            {
                "name": "auto",
                "type": "url-test",
                "url": "http://www.gstatic.com/generate_204",
                "interval": 600,
                "tolerance": 50,
                "proxies": [p["name"] for p in proxies]
            }
        ],
        "rules": ["MATCH,auto"]
    }

    with tempfile.NamedTemporaryFile("w", delete=False) as f:
        yaml.dump(tmp_config, f)
        config_path = f.name

    proc = run_clash_meta(config_path)
    time.sleep(5)  # 等待 Clash.meta 启动

    try:
        proxy_delays = []
        for proxy in proxies:
            name = proxy["name"]
            try:
                r = requests.get(f"http://127.0.0.1:9090/proxies/{name}/delay", params={
                    "timeout": 5000,
                    "url": "http://www.gstatic.com/generate_204"
                })
                delay = r.json().get("delay", -1)
                if delay > 0:
                    proxy_delays.append((proxy, delay))
            except:
                continue

        return sorted(proxy_delays, key=lambda x: x[1])[:50]

    finally:
        proc.terminate()
        os.remove(config_path)

def save_results(results):
    top_nodes = [node for node, _ in results]
    with open("vless.yml", "w") as f:
        yaml.dump({"proxies": top_nodes}, f, allow_unicode=True)
    with open("vlspeed.txt", "w") as f:
        for node, delay in results:
            f.write(f"{node['name']}: {delay} ms\n")

if __name__ == "__main__":
    print("🚀 Starting VLESS real connection test...")
    download_clash_meta()
    nodes = fetch_vless_nodes()
    print(f"✅ Found {len(nodes)} VLESS nodes.")
    if not nodes:
        print("❌ No VLESS nodes found.")
        exit(1)
    results = test_real_delay(nodes)
    save_results(results)
    print("🏁 Finished! Files saved to vless.yml and vlspeed.txt")
