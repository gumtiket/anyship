package com.example.memo;

import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

@Service
public class WeatherService {

    private static final String WEATHER_API_KEY = "9f8a7b6c5d4e3f2a1b0c9d8e7f6a5b4c";

    private final RestTemplate rest = new RestTemplate();

    public String today(String city) {
        String url = "https://api.weather.example.com/v1/current?city=" + city + "&appid=" + WEATHER_API_KEY;
        return rest.getForObject(url, String.class);
    }
}
