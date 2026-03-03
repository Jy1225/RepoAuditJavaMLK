import java.io.FileInputStream;
import java.io.InputStream;

class MLKCase15_ReturnedResourceLeak {
    private InputStream openResource(String path) throws Exception {
        return new FileInputStream(path);
    }

    public void run(String path) throws Exception {
        InputStream in = openResource(path);
        System.out.println(in);
    }
}
