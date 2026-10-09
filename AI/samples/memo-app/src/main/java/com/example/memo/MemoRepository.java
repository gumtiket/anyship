package com.example.memo;

import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;

public interface MemoRepository extends JpaRepository<Memo, Long> {

    // 최근 하루 안에 만든 메모
    @Query(value = "SELECT * FROM memo WHERE created_at > datetime('now', '-1 day')", nativeQuery = true)
    List<Memo> findRecent();
}
