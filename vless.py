#!/usr/bin/env python3
import os
import time
import subprocess
import yaml
import json
import concurrent.futures
from urllib.parse import urlparse

DEBUG = True
TIMEOUT = 15  # 测试超时时间(秒)
TEST_URL = "https://www.gstatic.com/generate_204"
MAX_WORKERS = 20  # 并发测试线程数
TOP_NODES = 50    # 保留的最佳节点数

def log(message):
    """日志记录函数"""
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    log_msg = f"[{timestamp}] {message}"
    print(log_msg)
    with open("vless.log", "a", encoding='utf-8') as f:
        f.write(log_msg + "\n")

def run_xray_test(config):
    """通过Xray核心测试节点"""
    try:
        # 写入临时配置
        with open("temp_config.json", "w", encoding='utf-8') as f:
            json.dump(config, f)
        
        # 启动Xray
        xray_cmd = ['xray', 'run', '-c', 'temp_config.json']
        curl_cmd = [
            'curl', '-sS',
            '--connect-timeout', '10',
            '--max-time', str(TIMEOUT),
            '--socks5-hostname', '127.0.0.1:1080',
            '-o', '/dev/null',
            '-w', '%{http_code} %{time_total}',
            TEST_URL
        ]
        
        start_time = time.time()
        with subprocess.Popen(xray_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as xray_proc:
            time.sleep(2)  # 等待Xray启动
            
            try:
                result = subprocess.run(
                    curl_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=TIMEOUT
                )
                
                if result.returncode == 0 and '204' in result.stdout:
                    latency = float(result.stdout.split()[1]) * 1000  # 转为毫秒
                    return True, latency
                return False, None
                
            finally:
                xray_proc.terminate()
                xray_proc.wait()
                
    except Exception as e:
        log(f"测试异常: {str(e)}")
        return False, None
    finally:
        if os.path.exists("temp_config.json"):
            os.remove("temp_config.json")

def test_vless_node(node):
    """测试单个VLESS节点"""
    try:
        if node.get('type', '').lower() != 'vless':
            return None
            
        # 构建Xray配置
        config = {
            "inbounds": [{
                "port": 1080,
                "protocol": "socks",
                "listen": "127.0.0.1",
                "settings": {"auth": "noauth"}
            }],
            "outbounds": [{
                "protocol": "vless",
                "settings": {
                    "vnext": [{
                        "address": node['server'],
                        "port": int(node['port']),
                        "users": [{
                            "id": node['uuid'],
                            "encryption": node.get('encryption', 'none'),
                            "flow": node.get('flow', '')
                        }]
                    }]
                },
                "streamSettings": node.get('streamSettings', {})
            }]
        }
        
        success, latency = run_xray_test(config)
        if success:
            log(f"✅ {node.get('name', '未知节点')} 有效 | 延迟: {latency:.2f}ms")
            return {
                'node': node,
                'latency': latency,
                'time': time.strftime('%Y-%m-%d %H:%M:%S')
            }
        else:
            log(f"❌ {node.get('name', '未知节点')} 无效")
            return None
            
    except Exception as e:
        log(f"测试 {node.get('name', '未知节点')} 时出错: {str(e)}")
        return None

def load_nodes(sources):
    """从多个源加载节点"""
    all_nodes = []
    for url in sources:
        try:
            log(f"正在加载节点源: {url}")
            result = subprocess.run(
                ['curl', '-sSL', url],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=30
            )
            data = yaml.safe_load(result.stdout)
            vless_nodes = [n for n in data.get('proxies', []) 
                         if isinstance(n, dict) and n.get('type', '').lower() == 'vless']
            all_nodes.extend(vless_nodes)
            log(f"📥 从 {url} 加载 {len(vless_nodes)} 个VLESS节点")
        except Exception as e:
            log(f"❌ 加载 {url} 失败: {str(e)}")
    return all_nodes

def deduplicate_nodes(nodes):
    """节点去重"""
    seen = set()
    unique_nodes = []
    for node in nodes:
        key = f"{node.get('type')}_{node.get('server')}_{node.get('port')}_{node.get('uuid')}"
        if key not in seen:
            seen.add(key)
            unique_nodes.append(node)
    log(f"🔍 去重后VLESS节点数: {len(unique_nodes)}")
    return unique_nodes

def main():
    # 确保输出目录存在
    os.makedirs("output", exist_ok=True)
    
    # 加载节点源
    sources = [
        "https://cdn.jsdelivr.net/gh/0xJins/x.sub@main/trials_providers/TW.yaml",
        "https://cdn.jsdelivr.net/gh/1wyy/tg_mfbpn_sub@main/trial.yaml"
    ]
    nodes = load_nodes(sources)
    nodes = deduplicate_nodes(nodes)
    
    # 并发测试
    valid_nodes = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(test_vless_node, node): node for node in nodes}
        
        for future in concurrent.futures.as_completed(futures):
            try:
                result = future.result()
                if result:
                    valid_nodes.append(result)
            except Exception as e:
                log(f"并发测试出错: {str(e)}")
    
    # 筛选最佳节点
    valid_nodes.sort(key=lambda x: x['latency'])
    best_nodes = valid_nodes[:TOP_NODES]
    
    # 生成结果文件
    if best_nodes:
        # 生成vless.yml
        with open("output/vless.yml", "w", encoding='utf-8') as f:
            yaml.safe_dump(
                {"proxies": [n['node'] for n in best_nodes]},
                f,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False
            )
        
        # 生成vlspeed.txt
        with open("output/vlspeed.txt", "w", encoding='utf-8') as f:
            f.write("VLESS节点速度排行 (延迟从低到高)\n")
            f.write("="*60 + "\n")
            f.write(f"测试时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"测试URL: {TEST_URL}\n")
            f.write("="*60 + "\n\n")
            
            for idx, node in enumerate(best_nodes, 1):
                info = node['node']
                f.write(f"{idx:2d}. {info.get('name', '未知节点')}\n")
                f.write(f"   地址: {info['server']}:{info['port']}\n")
                f.write(f"   协议: {info.get('network', 'tcp')}\n")
                f.write(f"   延迟: {node['latency']:.2f}ms\n")
                f.write(f"   UUID: {info['uuid'][:8]}...\n")
                f.write(f"   测试时间: {node['time']}\n")
                f.write("-"*60 + "\n")
        
        log(f"🎉 生成 {len(best_nodes)} 个最佳VLESS节点")
    else:
        log("❌ 未找到有效VLESS节点")
        # 创建空文件确保工作流继续
        open("output/vless.yml", "w").close()
        open("output/vlspeed.txt", "w").close()

if __name__ == '__main__':
    log("=== VLESS节点测试开始 ===")
    try:
        main()
    except Exception as e:
        log(f"!!! 主程序出错: {str(e)}")
        raise