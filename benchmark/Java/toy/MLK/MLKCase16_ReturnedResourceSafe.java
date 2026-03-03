import java.io.FileInputStream;
import java.io.InputStream;

class MLKCase16_ReturnedResourceSafe {
    private InputStream openResource(String path) throws Exception {
        return new FileInputStream(path);
    }

    public void run(String path) throws Exception {
        InputStream in = openResource(path);
        in.close();
    }
}
