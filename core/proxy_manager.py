import aiohttp
import asyncio
import logging

logger = logging.getLogger("MoltyBot.ProxyManager")

class ProxyManager:
    SOURCES = [
        "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/http.txt",
        "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt",
        "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt"
    ]

    @classmethod
    async def scrape_free_proxies(cls):
        """Scrape proxies from public GitHub lists."""
        found = []
        logger.info("Scraping public proxies...")
        async with aiohttp.ClientSession() as session:
            for url in cls.SOURCES:
                try:
                    async with session.get(url, timeout=10) as resp:
                        if resp.status == 200:
                            text = await resp.text()
                            proxies = [f"http://{line.strip()}" for line in text.split('\n') if line.strip()]
                            found.extend(proxies)
                except: continue
        return list(set(found))

    @classmethod
    async def test_proxy(cls, proxy_url: str):
        """Test if proxy can reach Molty Royale API."""
        test_url = "https://cdn.moltyroyale.com/api/games?status=waiting"
        try:
            async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
                async with session.get(test_url, proxy=proxy_url, timeout=8) as resp:
                    return resp.status == 200
        except:
            return False

    @classmethod
    async def get_healthy_proxies(cls, custom_list=None, target_count=55):
        """Filter and return only working proxies."""
        raw_list = custom_list if custom_list else await cls.scrape_free_proxies()
        if not raw_list: return []

        logger.info(f"Testing proxies... this might take a minute.")
        healthy = []
        
        # Test in batches of 50 to avoid local OS limits
        batch_size = 50
        for i in range(0, min(len(raw_list), 500), batch_size):
            batch = raw_list[i:i+batch_size]
            tasks = [cls.test_proxy(p) for p in batch]
            results = await asyncio.gather(*tasks)
            
            for idx, is_ok in enumerate(results):
                if is_ok:
                    healthy.append(batch[idx])
                    if len(healthy) >= target_count: break
            
            if len(healthy) >= target_count: break
            await asyncio.sleep(1) # Small pause between batches

        logger.info(f"Found {len(healthy)} healthy proxies.")
        return healthy
