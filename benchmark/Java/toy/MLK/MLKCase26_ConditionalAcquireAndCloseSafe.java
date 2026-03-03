import java.io.FileInputStream;
import java.io.InputStream;

class MLKCase26_ConditionalAcquireAndCloseSafe {
    public void run(String path, boolean enabled) throws Exception {
        if (enabled) {
            InputStream in = new FileInputStream(path);
            in.close();
        }
    }
}
