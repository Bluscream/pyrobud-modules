import asyncio, json
from ipaddress import IPv4Address

try:
    from aiohttp import ClientSession
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False
    ClientSession = None

from .IpApi import IPAPIResponse, ipapi_response_from_dict

class DataCenter(object):
    def __init__(self, id: int, code: str = "???") -> None:
        self.id: int = id
        self.code: str = code
        self.geo: IPAPIResponse = None
        self.endpoints: set[tuple[IPv4Address, int]] = set()
        self.ping: int = -1
        self.status: int = -1
        self.last_down: int = -1
        self.last_lag: int = -1

class DataCenters(object):
    ipapi_url: str = "http://ip-api.com/json/{ip}?fields=66846719"
    list_url: str = "https://core.telegram.org/getProxyConfig"
    update_url: str = "https://raw.githubusercontent.com/OctoGramApp/assets/master/DCStatus/dc_status.json"

    def __init__(self) -> None:
        if not AIOHTTP_AVAILABLE:
            raise ImportError("aiohttp is required for DataCenters class")
        self.http: ClientSession = ClientSession()
        self.dcs: dict[int, DataCenter] = {}

    def add_or_update(self, id, code: str = None, geo: IPAPIResponse = None, ip: IPv4Address = None, port: int = None, ping: int = None, status: int = None, last_down: int = None, last_lag: int = None) -> DataCenter:
        """Add or update a DataCenter with the given properties."""
        # Normalize ID (remove hyphens and convert to int)
        id = int(str(id).replace('-', ''))
        
        # Create new DataCenter if it doesn't exist
        if id not in self.dcs:
            self.dcs[id] = DataCenter(id, code or "???")
        
        dc = self.dcs[id]
        
        # Update properties if provided
        if code is not None:
            dc.code = code
        if geo is not None:
            dc.geo = geo
        if ping is not None:
            dc.ping = ping
        if status is not None:
            dc.status = status
        if last_down is not None:
            dc.last_down = last_down
        if last_lag is not None:
            dc.last_lag = last_lag
        if ip is not None:
            dc.endpoints.add((ip, port or 8888))
        
        return dc

    async def update(self):
        """Update DataCenter information from Telegram's proxy config and external APIs."""
        try:
            # Fetch proxy configuration
            async with self.http.get(self.list_url) as resp:
                dc_list: list[str] = (await resp.text()).split("\n")
                for line in dc_list:
                    if not line.strip() or not line.startswith("proxy_for "):
                        continue
                    
                    try:
                        parts = line.split(" ")
                        if len(parts) < 3:
                            continue
                        
                        dc_id = parts[1]
                        ip_port = parts[2].split(":")
                        
                        if len(ip_port) < 2:
                            continue
                        
                        ip = IPv4Address(ip_port[0])
                        port = int(ip_port[1].replace(';', ''))
                        
                        self.add_or_update(id=dc_id, ip=ip, port=port)
                        print(f"Added DC{dc_id}: {ip}:{port}")
                    except (ValueError, IndexError) as ex:
                        print(f"Failed to parse line '{line}': {ex}")
                        continue
            
            print(f"Got list of {len(self.dcs)} DataCenters")
        except Exception as ex:
            print(f"Failed to fetch datacenter list: {ex}")

        # Fetch geo info for each datacenter
        for dc in self.dcs.values():
            if dc.geo:  # Skip if already has geo info
                continue
            
            for endpoint in dc.endpoints:
                try:
                    ip = endpoint[0]
                    print(f"Getting ip info for DC{dc.id}, Server {ip}")
                    async with self.http.get(self.ipapi_url.format(ip=ip)) as resp:
                        apiresp: IPAPIResponse = ipapi_response_from_dict(json.loads(await resp.text()))
                        if apiresp and apiresp.status == "success":
                            dc.geo = apiresp
                            print(f"Got ipapi response for DC{dc.id}")
                            break  # Only need one successful geo lookup per DC
                except Exception as ex:
                    print(f"Failed to get geo info for DC{dc.id} endpoint {ip}: {ex}")

        # Fetch status updates
        try:
            async with self.http.get(self.update_url) as resp:
                data: dict = json.loads(await resp.text())
                if "status" in data:
                    for _dc in data["status"]:
                        try:
                            dc = self.add_or_update(id=_dc["dc_id"])
                            dc.ping = _dc.get("ping", -1)
                            dc.status = _dc.get("dc_status", -1)
                            dc.last_down = _dc.get("last_down", -1)
                            dc.last_lag = _dc.get("last_lag", -1)
                        except Exception as ex:
                            print(f"Failed to update DC status: {ex}")
        except Exception as ex:
            print(f"Failed to fetch datacenter status updates: {ex}")
        
        print(f"Updated {len(self.dcs)} DataCenters")

        # Print summary
        for id, dc in self.dcs.items():
            geo_info = f"{dc.geo.continent}" if dc.geo else "No geo info"
            print(f"DC {id}: {geo_info} ({len(dc.endpoints)} endpoints)")