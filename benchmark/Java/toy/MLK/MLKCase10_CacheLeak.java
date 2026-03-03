import java.util.HashMap;
import java.util.Map;

class MLKCase10_CacheLeak {
    private final Map<String, Object> cache = new HashMap<>();

    public void putValue(String key, Object value) {
        cache.put(key, value);
    }
}
