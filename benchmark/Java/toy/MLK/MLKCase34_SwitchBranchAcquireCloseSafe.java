import java.io.FileInputStream;
import java.io.InputStream;

class MLKCase34_SwitchBranchAcquireCloseSafe {
    public void run(String path, int mode) throws Exception {
        switch (mode) {
            case 0:
                InputStream in = new FileInputStream(path);
                in.close();
                break;
            default:
                break;
        }
    }
}
