import asyncio
import socket
import time
from typing import Optional, Tuple

from .. import module
from .classes.DataCenter import DataCenters


class StartupModule(module.Module):
    name = "Startup"
    disabled = False

    async def _dns_resolve(self, hostname: str) -> Tuple[Optional[str], float]:
        """Resolve DNS and return (IP, duration_ms)."""
        start = time.perf_counter()
        try:
            loop = asyncio.get_event_loop()
            # Run getaddrinfo in executor to avoid blocking
            addr_info = await loop.run_in_executor(
                None,
                socket.getaddrinfo,
                hostname,
                None,
                socket.AF_INET,
                socket.SOCK_STREAM
            )
            duration = (time.perf_counter() - start) * 1000
            ip = addr_info[0][4][0] if addr_info else None
            return ip, duration
        except Exception as ex:
            duration = (time.perf_counter() - start) * 1000
            print(f"  ❌ DNS resolution failed for {hostname}: {ex}")
            return None, duration

    async def _tcp_ping(self, host: str, port: int = 443, timeout: float = 5.0) -> Tuple[bool, float]:
        """TCP ping and return (success, duration_ms)."""
        start = time.perf_counter()
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=timeout
            )
            duration = (time.perf_counter() - start) * 1000
            writer.close()
            await writer.wait_closed()
            return True, duration
        except asyncio.TimeoutError:
            duration = (time.perf_counter() - start) * 1000
            print(f"  ❌ TCP connection to {host}:{port} timed out after {duration:.1f}ms")
            return False, duration
        except Exception as ex:
            duration = (time.perf_counter() - start) * 1000
            print(f"  ❌ TCP connection to {host}:{port} failed: {ex}")
            return False, duration

    async def _run_diagnostics(self) -> None:
        """Run startup network diagnostics."""
        print("\n" + "="*60)
        print("🔍 STARTUP NETWORK DIAGNOSTICS")
        print("="*60)
        
        # DNS Resolution Tests
        print("\n📡 DNS Resolution Tests:")
        dns_targets = [
            "telegram.org",
            "api.telegram.org",
            "149.154.167.51",  # Direct IP (should be instant)
        ]
        
        total_dns_time = 0.0
        for hostname in dns_targets:
            ip, duration = await self._dns_resolve(hostname)
            if ip:
                print(f"  ✅ {hostname:20s} → {ip:15s} ({duration:6.1f}ms)")
                total_dns_time += duration
            else:
                print(f"  ❌ {hostname:20s} → Failed ({duration:6.1f}ms)")
        
        avg_dns = total_dns_time / len(dns_targets) if dns_targets else 0
        print(f"  📊 Average DNS time: {avg_dns:.1f}ms")
        
        # TCP Ping Tests
        print("\n🌐 Telegram Server Connectivity Tests:")
        tcp_targets = [
            ("149.154.167.51", 443, "DC2 (Amsterdam)"),
            ("149.154.175.50", 443, "DC1 (Miami)"),
            ("149.154.167.50", 443, "DC2 Alt"),
        ]
        
        total_tcp_time = 0.0
        successful_pings = 0
        for host, port, description in tcp_targets:
            success, duration = await self._tcp_ping(host, port, timeout=5.0)
            if success:
                print(f"  ✅ {description:20s} {host}:{port:3d} ({duration:6.1f}ms)")
                total_tcp_time += duration
                successful_pings += 1
            else:
                print(f"  ❌ {description:20s} {host}:{port:3d} (Failed)")
        
        if successful_pings > 0:
            avg_tcp = total_tcp_time / successful_pings
            print(f"  📊 Average ping time: {avg_tcp:.1f}ms ({successful_pings}/{len(tcp_targets)} successful)")
        else:
            print(f"  ⚠️  All connectivity tests failed!")
        
        print("\n" + "="*60 + "\n")

    async def on_load(self) -> None:
        """Initialize DataCenters and run startup diagnostics."""
        # Run network diagnostics first
        try:
            await self._run_diagnostics()
        except Exception as ex:
            print(f"Warning: Diagnostics failed: {ex}")
        
        # Initialize DataCenters
        try:
            print("Initializing bot.dc")
            self.bot.dc = DataCenters()
            await self.bot.dc.update()
            
            print("DataCenters initialized successfully:")
            for id, dc in self.bot.dc.dcs.items():
                geo_info = f"{dc.geo.continent}" if dc.geo else "No geo info"
                print(f"  DC{id}: {geo_info} ({len(dc.endpoints)} endpoints)")
        except ImportError as ex:
            print(f"Warning: DataCenters not available: {ex}")
            self.bot.dc = None
        except Exception as ex:
            print(f"Error initializing DataCenters: {ex}")
            self.bot.dc = None