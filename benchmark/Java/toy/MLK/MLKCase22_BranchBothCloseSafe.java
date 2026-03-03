import java.io.FileInputStream;
import java.io.InputStream;

class MLKCase22_BranchBothCloseSafe {
    public void run(String path, boolean preferFastPath) throws Exception {
        InputStream in = new FileInputStream(path);
        if (preferFastPath) {
            in.close();
        } else {
            in.close();
        }
    }
}
