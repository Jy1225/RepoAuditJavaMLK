import java.util.ArrayList;
import java.util.List;

class MLKCase07_CollectionSafe {
    private final List<Object> cache = new ArrayList<>();

    public void addAndClear(Object item) {
        cache.add(item);
        cache.clear();
    }
}
