-- Single table for activity tracking (MySQL timesheet_db)
CREATE TABLE IF NOT EXISTS activity_states (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    status ENUM('start','off','idle') NOT NULL,
    start_time DATETIME NULL,
    end_time DATETIME NULL,
    idle_at DATETIME NULL,
    idle_duration_seconds INT NULL,
    idle_duration_display VARCHAR(20) NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_user (user_id),
    INDEX idx_status (status),
    INDEX idx_idle_at (idle_at)
);
