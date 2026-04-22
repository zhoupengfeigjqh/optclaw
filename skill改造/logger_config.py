import logging
import datetime
import os

def cleanup_old_logs():
    # 获取当前日期
    current_date = datetime.datetime.now()
    # 计算5天前的日期
    five_days_ago = current_date - datetime.timedelta(days=5)
    # 日志文件所在目录（这里假设日志文件和代码在同一目录，可根据实际情况修改）
    log_dir = os.path.dirname(os.path.abspath(__file__))
    # 遍历目录下的文件
    for file in os.listdir(log_dir):
        file_path = os.path.join(log_dir, file)
        # 检查是否是预测日志文件
        if file.startswith("prediction_") and file.endswith(".log"):
            # 提取日志文件的日期部分
            try:
                log_date_str = file.split("_")[1].split(".")[0]
                log_date = datetime.datetime.strptime(log_date_str, "%Y-%m-%d")
                # 如果日志日期在5天前，删除该文件
                if log_date < five_days_ago:
                    os.remove(file_path)
                    print(f"Deleted old log file: {file_path}")
            except (IndexError, ValueError):
                # 若文件命名不符合预期，跳过
                continue


def setup_logging(name):
    # appendix = datetime.datetime.now().strftime("%Y-%m-%d")
    cleanup_old_logs()
    logging.basicConfig(
        level=logging.INFO,
        format="format='%(asctime)s - %(name)s - %(funcName)s - %(levelname)s - %(message)s'",
        handlers=[
            logging.FileHandler(f"prediction_{datetime.datetime.now().strftime('%Y-%m-%d')}.log"),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(name)