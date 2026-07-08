CREATE DATABASE IF NOT EXISTS skyguard DEFAULT CHARSET utf8mb4;
USE skyguard;

CREATE TABLE IF NOT EXISTS user (
    user_id       INT AUTO_INCREMENT PRIMARY KEY,
    username      VARCHAR(50)  NOT NULL UNIQUE,
    email         VARCHAR(100) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    create_time   DATETIME     DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS task (
    task_id       INT AUTO_INCREMENT PRIMARY KEY,
    user_id       INT         NOT NULL,
    task_name     VARCHAR(100) NOT NULL,
    disaster_type VARCHAR(50),
    location      VARCHAR(100),
    status        ENUM('IDLE','RUNNING','DONE','ERROR') DEFAULT 'IDLE',
    create_time   DATETIME    DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES user(user_id)
);

CREATE TABLE IF NOT EXISTS conversation (
    conv_id    INT AUTO_INCREMENT PRIMARY KEY,
    task_id    INT  NOT NULL,
    role       ENUM('user','assistant','tool') NOT NULL,
    content    TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (task_id) REFERENCES task(task_id)
);

CREATE TABLE IF NOT EXISTS document (
    doc_id      INT AUTO_INCREMENT PRIMARY KEY,
    task_id     INT          NOT NULL,
    filename    VARCHAR(255) NOT NULL,
    file_type   VARCHAR(20),
    file_path   VARCHAR(500) NOT NULL,
    upload_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (task_id) REFERENCES task(task_id)
);
