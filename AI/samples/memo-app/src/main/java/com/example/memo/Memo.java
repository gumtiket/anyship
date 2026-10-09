package com.example.memo;

import jakarta.persistence.*;
import java.time.LocalDateTime;

@Entity
public class Memo {
    @Id @GeneratedValue
    private Long id;
    private String title;
    private String content;
    private String imagePath;
    private LocalDateTime createdAt;

    public Long getId() { return id; }
    public String getTitle() { return title; }
    public void setTitle(String title) { this.title = title; }
    public String getContent() { return content; }
    public void setContent(String content) { this.content = content; }
    public String getImagePath() { return imagePath; }
    public void setImagePath(String imagePath) { this.imagePath = imagePath; }
}
