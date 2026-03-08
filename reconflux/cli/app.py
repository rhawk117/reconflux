import dataclasses as dc
import logging
import tomllib
from pathlib import Path

from reconflux.logging import LoggingConfig, initialize_logging

logger = logging.getLogger(__name__)


@dc.dataclass(slots=True)
class SettingsFolder:
    folder_name: str = 'settings'
    folder_path: Path = dc.field(init=False)

    def __post_init__(self) -> None:
        self.folder_path = Path(self.folder_name).resolve()
        self.folder_path.mkdir(exist_ok=True)


    def get_file_path(self, filename: str) -> Path:
        return self.folder_path.joinpath(filename).resolve()


    def get_logger_config(self, filename: str = 'logger.toml') -> LoggingConfig:
        logger_path = self.get_file_path(filename)
        if not logger_path.exists():
            default_config = LoggingConfig()
            # create the toml file
            return default_config

        toml_contents = tomllib.loads(logger_path.read_text('utf-8'))
        logger_config = LoggingConfig.model_validate(toml_contents)
        return logger_config



def setup_logger(settings_folder: SettingsFolder) -> None:
    logger_config = settings_folder.get_logger_config()
    initialize_logging(logger_config)
    logger.info('Logger initialized')



class IPInfoDemo:

    def __init__(self) -> None:







def main() -> None:
    settings_folder = SettingsFolder()
    setup_logger(settings_folder)




if __name__ == '__main__':
    main()
