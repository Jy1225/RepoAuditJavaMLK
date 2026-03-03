import java.util.HashMap;
import java.util.Map;

class MLKCase11_CacheSafe {
    private final Map<String, Object> cache = new HashMap<>();

    public void putAndRemove(String key, Object value) {
        cache.put(key, value);
        cache.remove(key);
    }
}
