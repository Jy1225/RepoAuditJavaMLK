import java.util.ArrayList;
import java.util.List;

class MLKCase06_CollectionLeak {
    private final List<Object> cache = new ArrayList<>();

    public void add(Object item) {
        cache.add(item);
    }
}
