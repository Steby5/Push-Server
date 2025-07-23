import asyncio
import argparse
from backend.service_manager import ServiceManager  # Adjust this import if needed

def main():
    parser = argparse.ArgumentParser(description="Service Manager CLI/GUI")
    parser.add_argument('--gui', action='store_true', help='Run in GUI mode')
    args = parser.parse_args()

    if args.gui:
        print("GUI mode is not yet implemented.")
        # Placeholder for GUI launch
        # from frontend.gui import run_gui
        # run_gui()
    else:
        async def run_services():
            manager = ServiceManager()
            try:
                await manager.start_services()
                print("Services started. Press Ctrl+C to stop.")
                while True:
                    await asyncio.sleep(1)
            except KeyboardInterrupt:
                print("\nStopping services...")
                await manager.stop_all_services()
                print("Shutdown complete.")

        try:
            asyncio.run(run_services())
        except KeyboardInterrupt:
            pass  # Suppress traceback on Ctrl+C

if __name__ == "__main__":
    main()