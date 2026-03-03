import java.io.FileInputStream;
import java.io.InputStream;

class MLKCase20_FinallyHelperCloseSafe {
    private void closeResource(InputStream in) throws Exception {
        in.close();
    }

    public void run(String path) throws Exception {
        InputStream in = new FileInputStream(path);
        try {
            System.out.println(in.read());
        } finally {
            closeResource(in);
        }
    }
}
