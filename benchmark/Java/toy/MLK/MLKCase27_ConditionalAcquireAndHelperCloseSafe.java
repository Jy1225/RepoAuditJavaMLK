import java.io.FileInputStream;
import java.io.InputStream;

class MLKCase27_ConditionalAcquireAndHelperCloseSafe {
    private void closeResource(InputStream in) throws Exception {
        in.close();
    }

    public void run(String path, boolean enabled) throws Exception {
        if (enabled) {
            InputStream in = new FileInputStream(path);
            closeResource(in);
        }
    }
}
