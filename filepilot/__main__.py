import sys


def main() -> int:
    if len(sys.argv) > 1:
        from .cli import main as cli_main
        return cli_main(sys.argv[1:])
    try:
        from .ui.main_window import run
    except ImportError:
        print("Графический интерфейс появится на следующем этапе. Пока доступна консоль: python -m filepilot --help")
        return 0
    return run()


if __name__ == "__main__":
    sys.exit(main())
