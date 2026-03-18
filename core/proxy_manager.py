import aiohttp
import asyncio
import logging
from typing import List, Dict
from aiohttp_socks import ProxyConnector

logger = logging.getLogger("MoltyBot.ProxyManager")

class ProxyManager:
    # Sumber proxy publik yang lebih luas (HTTP, SOCKS4, SOCKS5)
    SOURCES = {
        "http": [
            "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/http.txt",
            "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
            "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt"
        ],
        "socks4": [
            "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/socks4.txt",
            "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks4.txt"
        ],
        "socks5": [
            "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/socks5.txt",
            "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks5.txt"
        ]
    }

    @classmethod
    async def scrape_free_proxies(cls) -> List[str]:
        """Scrape all types of proxies and format them correctly."""
        found = []
        logger.info("Scraping high-quality public proxies (HTTP/SOCKS)...")
        
        async with aiohttp.ClientSession() as session:
            for proto, urls in cls.SOURCES.items():
                for url in urls:
                    try:
                        async with session.get(url, timeout=10) as resp:
                            if resp.status == 200:
                                text = await resp.text()
                                for line in text.split('\n'):
                                    proxy = line.strip()
                                    if proxy and ":" in proxy:
                                        # Format: protocol://host:port
                                        found.append(f"{proto}://{proxy}")
                    except: continue
        
        # Remove duplicates
        unique_found = list(set(found))
        logger.info(f"Scraped {len(unique_found)} potential proxies.")
        return unique_found

    @classmethod
    async def test_proxy(cls, proxy_url: str):
        """Test proxy against Molty Royale API with SOCKS support."""
        test_url = "https://cdn.moltyroyale.com/api/games?status=waiting"
        try:
            # Menggunakan connector khusus untuk SOCKS support
            connector = ProxyConnector.from_url(proxy_url, ssl=False)
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.get(test_url, timeout=12) as resp:
                    # Kita anggap hidup jika membalas 200 OK
                    return resp.status == 200
        except:
            return False

    @classmethod
    async def get_healthy_proxies(cls, custom_list=None, target_count=55):
        """Intelligent filtering: test until target count is reached."""
        raw_list = custom_list if custom_list else await cls.scrape_free_proxies()
        if not raw_list: return []

        logger.info(f"Validating proxies... Target: {target_count}")
        healthy = []
        
        # Shuffle agar tidak selalu mencoba proxy yang sama di setiap restart
        import random
        random.shuffle(raw_list)

        # Test in small batches to be efficient
        batch_size = 25
        for i in range(0, len(raw_list), batch_size):
            batch = raw_list[i:i+batch_size]
            tasks = [cls.test_proxy(p) for p in batch]
            results = await asyncio.gather(*tasks)
            
            for idx, is_ok in enumerate(results):
                if is_ok:
                    healthy.append(batch[idx])
                    if len(healthy) >= target_count: break
            
            logger.info(f"Progress: {len(healthy)}/{target_count} healthy proxies found...")
            if len(healthy) >= target_count: break
            
            # Anti-flood local network
            await asyncio.sleep(0.5)

        logger.info(f"Validation complete. Total healthy: {len(healthy)}")
        return healthy
