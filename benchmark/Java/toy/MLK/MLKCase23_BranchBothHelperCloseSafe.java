import java.io.FileInputStream;
import java.io.InputStream;

class MLKCase23_BranchBothHelperCloseSafe {
    private void closeResource(InputStream in) throws Exception {
        in.close();
    }

    public void run(String path, boolean preferFastPath) throws Exception {
        InputStream in = new FileInputStream(path);
        if (preferFastPath) {
            closeResource(in);
        } else {
            closeResource(in);
        }
    }
}
