
from .. import module
from .classes.DataCenter import DataCenters


class StartupModule(module.Module):
    name = "Startup"
    disabled = False

    async def on_load(self) -> None:
        """Initialize DataCenters and update information."""
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