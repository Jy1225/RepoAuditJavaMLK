import java.io.FileInputStream;
import java.io.InputStream;

class MLKCase18_FinallyCloseSafe {
    public void run(String path) throws Exception {
        InputStream in = new FileInputStream(path);
        try {
            System.out.println(in.read());
        } finally {
            in.close();
        }
    }
}
