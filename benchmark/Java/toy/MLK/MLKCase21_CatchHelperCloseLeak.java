import java.io.FileInputStream;
import java.io.InputStream;

class MLKCase21_CatchHelperCloseLeak {
    private void releaseInHelper(InputStream in) throws Exception {
        in.close();
    }

    public void run(String path) throws Exception {
        InputStream in = new FileInputStream(path);
        try {
            System.out.println(in.read());
        } catch (Exception ex) {
            releaseInHelper(in);
        }
    }
}
