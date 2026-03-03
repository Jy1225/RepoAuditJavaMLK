import java.io.FileInputStream;
import java.io.InputStream;

class MLKCase13_HelperCloseSafe {
    private void closeResource(InputStream in) throws Exception {
        in.close();
    }

    public void run(String path) throws Exception {
        InputStream in = new FileInputStream(path);
        closeResource(in);
    }
}
