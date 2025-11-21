from typing import Optional


class Config:
    def __init__(self) -> None:
        pass

    ADDRESS: str = "10.30.1.118"
    PORT: int = 443
    PROTOCOL: str = "https"
    USERNAME: str = "localtest"
    PASSWORD: Optional[str] = "100%wifi100%WIFI"
    VERIFY_SSL: bool = False
    USE_UNSAFE_COOKIE_JAR: bool = False
    DESTINATION_PATH: str = "./"
    USE_SUBFOLDERS: bool = False
    TOUCH_FILES: bool = False
    SKIP_EXISTING_FILES: bool = False
    IGNORE_FAILED_DOWNLOADS: bool = False
    DISABLE_ALIGNMENT: bool = False
    DISABLE_SPLITTING: bool = False
    DOWNLOAD_WAIT: int = 10
    DOWNLOAD_TIMEOUT: float = (60)
    MAX_RETRIES: int = 3
    USE_UTC_FILENAMES: bool = False
