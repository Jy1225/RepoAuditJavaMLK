import java.io.FileInputStream;
import java.io.InputStream;

class MLKCase19_CatchOnlyCloseLeak {
    public void run(String path) throws Exception {
        InputStream in = new FileInputStream(path);
        try {
            System.out.println(in.read());
        } catch (Exception ex) {
            in.close();
        }
    }
}
