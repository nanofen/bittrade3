import logging

def get_custom_logger(log_level="info"):

    log_level = log_level.lower()
    if log_level == "debug":
        log_level = logging.DEBUG
    elif log_level == "info":
        log_level = logging.INFO
    elif log_level == "warning":
        log_level = logging.WARNING
    elif log_level == "error":
        log_level = logging.ERROR
    elif log_level == "critical":
        log_level = logging.CRITICAL
    else:
        log_level = logging.WARNING

    # ログのフォーマットを設定
    log_format = "%(asctime)s [%(levelname)s] [%(filename)s:%(lineno)d] - %(message)s"

    # ファイルハンドラを作成
    file_handler = logging.FileHandler("logfile.log")
    file_handler.setLevel(log_level)
    file_handler.setFormatter(logging.Formatter(log_format))

    # 標準出力ハンドラを作成
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(logging.Formatter(log_format))

    # ロガーを作成
    logger = logging.getLogger()
    logger.setLevel(log_level)

    # ハンドラを追加
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger