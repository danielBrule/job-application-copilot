"""Creation and validation of private local application directories."""

from pathlib import Path

from job_application_copilot.config import AppSettings, load_settings


class LocalDirectoryError(RuntimeError):
    """Raised when a required local directory cannot be prepared."""

    def __init__(self, path: Path, reason: str) -> None:
        self.path = path
        super().__init__(f"Cannot prepare private directory '{path}': {reason}")


def required_local_directories(settings: AppSettings) -> tuple[Path, ...]:
    """Return required private directories in deterministic creation order."""

    directories = (
        settings.database_path.parent,
        settings.cv_folder,
        settings.logs_folder,
        settings.document_a_folder,
        settings.document_b_folder,
        settings.templates_folder,
        settings.french_examples_folder,
        settings.assessment_prompts_folder,
        settings.english_generation_prompts_folder,
        settings.french_generation_prompts_folder,
    )
    return tuple(dict.fromkeys(directories))


def ensure_local_directories(settings: AppSettings) -> tuple[Path, ...]:
    """Create required private directories and verify that each is a directory."""

    directories = required_local_directories(settings)
    for directory in directories:
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise LocalDirectoryError(directory, str(error)) from error

        if not directory.is_dir():
            raise LocalDirectoryError(directory, "the path exists but is not a directory")

    return directories


def main() -> None:
    """Prepare configured private directories for developer operations."""

    try:
        directories = ensure_local_directories(load_settings())
    except LocalDirectoryError as error:
        raise SystemExit(str(error)) from None

    print("Private directories are ready:")
    for directory in directories:
        print(f"- {directory}")


if __name__ == "__main__":
    main()
