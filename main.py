from pathlib import Path

from eq_optimizer.gui import launch_gui


def main() -> None:
    """Start the EQ Optimizer GUI with the default project store."""

    launch_gui(Path("project_store"))


if __name__ == "__main__":
    main()
