package com.example.memo;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.List;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

@RestController
@RequestMapping("/memos")
public class MemoController {

    private final MemoRepository repo;
    private final WeatherService weather;

    public MemoController(MemoRepository repo, WeatherService weather) {
        this.repo = repo;
        this.weather = weather;
    }

    @GetMapping
    public List<Memo> list() { return repo.findAll(); }

    @GetMapping("/recent")
    public List<Memo> recent() { return repo.findRecent(); }

    @GetMapping("/weather")
    public String weather(@RequestParam String city) { return weather.today(city); }

    @PostMapping("/{id}/image")
    public Memo upload(@PathVariable Long id, @RequestParam("file") MultipartFile file) throws IOException {
        Path dir = Path.of("uploads");
        Files.createDirectories(dir);
        Path target = dir.resolve(id + "-" + file.getOriginalFilename());
        Files.copy(file.getInputStream(), target, StandardCopyOption.REPLACE_EXISTING);
        Memo memo = repo.findById(id).orElseThrow();
        memo.setImagePath(target.toString());
        return repo.save(memo);
    }
}
